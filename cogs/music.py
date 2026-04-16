import asyncio
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)


@dataclass
class Track:
    title: str
    stream_url: str
    webpage_url: str
    duration: Optional[int]
    requested_by_id: int


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "Unknown"

    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


class Music(commands.Cog):
    """Simple YouTube music controls for low-resource hosting."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: Dict[int, List[Track]] = {}
        self.now_playing: Dict[int, Track] = {}
        self.text_channels: Dict[int, int] = {}

    def get_ffmpeg_executable(self) -> Optional[str]:
        custom_path = os.getenv("FFMPEG_PATH", "").strip()
        if custom_path and os.path.exists(custom_path):
            return custom_path
        return shutil.which("ffmpeg")

    def get_music_unavailable_reason(self) -> Optional[str]:
        if not self.is_supported_voice_runtime():
            return "Music is unavailable on this host right now. PebbleHost is running Python 3.13; switch to Python 3.11 or 3.12 for voice support."

        if not self.get_ffmpeg_executable():
            return "Music is unavailable because FFmpeg is not installed. Add FFmpeg or set FFMPEG_PATH in PebbleHost."

        if not self.get_cookies_file():
            return "Music is unavailable because YouTube cookies are not configured. Upload cookies.txt and set YTDLP_COOKIES_FILE in PebbleHost."

        return None

    def get_cookies_file(self) -> Optional[str]:
        cookies_file = os.getenv("YTDLP_COOKIES_FILE", "").strip()
        if cookies_file and os.path.exists(cookies_file):
            return cookies_file
        return None

    def is_supported_voice_runtime(self) -> bool:
        return sys.version_info < (3, 13)

    def get_ytdl_options(self) -> dict:
        options = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "default_search": "ytsearch",
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            # Helps on some hosts where the default client gets challenged.
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                }
            },
        }

        cookies_file = self.get_cookies_file()
        if cookies_file:
            options["cookiefile"] = cookies_file

        return options

    async def extract_track(self, query: str) -> Optional[Track]:
        query = query.strip()
        if not query:
            return None

        ytdl_options = self.get_ytdl_options()

        def blocking_extract() -> dict:
            with yt_dlp.YoutubeDL(ytdl_options) as ydl:
                return ydl.extract_info(query, download=False)

        try:
            info = await asyncio.to_thread(blocking_extract)
        except DownloadError as error:
            message = str(error)
            if "Sign in to confirm you" in message or "not a bot" in message:
                raise RuntimeError(
                    "YouTube blocked this request. Add a cookies.txt file and set YTDLP_COOKIES_FILE, "
                    "or try a different video/search query."
                ) from error
            raise RuntimeError("yt-dlp could not load this track.") from error

        if "entries" in info:
            entries = [entry for entry in info.get("entries", []) if entry]
            if not entries:
                return None
            info = entries[0]

        stream_url = info.get("url")
        if not stream_url:
            return None

        return Track(
            title=info.get("title") or "Unknown title",
            stream_url=stream_url,
            webpage_url=info.get("webpage_url") or query,
            duration=info.get("duration"),
            requested_by_id=0,
        )

    async def start_track(self, guild: discord.Guild, track: Track):
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return

        ffmpeg_path = self.get_ffmpeg_executable()
        if not ffmpeg_path:
            logger.error("FFmpeg not found while attempting playback for guild %s", guild.id)
            return

        self.now_playing[guild.id] = track

        source = discord.FFmpegPCMAudio(
            track.stream_url,
            executable=ffmpeg_path,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn -loglevel warning",
        )

        def after_playback(error: Optional[Exception]):
            if error:
                logger.error("Playback error in guild %s: %s", guild.id, error)
            self.bot.loop.call_soon_threadsafe(asyncio.create_task, self.play_next(guild.id))

        voice_client.play(source, after=after_playback)

        channel_id = self.text_channels.get(guild.id)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            requester = guild.get_member(track.requested_by_id)
            requester_text = requester.mention if requester else "Unknown"
            embed = discord.Embed(
                title="Now Playing",
                description=f"[{track.title}]({track.webpage_url})",
                color=discord.Color.green(),
            )
            embed.add_field(name="Duration", value=format_duration(track.duration), inline=True)
            embed.add_field(name="Requested by", value=requester_text, inline=True)
            await channel.send(embed=embed)

    async def play_next(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            self.queues.pop(guild_id, None)
            self.now_playing.pop(guild_id, None)
            self.text_channels.pop(guild_id, None)
            return

        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            self.queues.pop(guild_id, None)
            self.now_playing.pop(guild_id, None)
            self.text_channels.pop(guild_id, None)
            return

        queue = self.queues.get(guild_id, [])
        if not queue:
            self.now_playing.pop(guild_id, None)
            return

        next_track = queue.pop(0)
        await self.start_track(guild, next_track)

    @app_commands.command(name="play", description="Play audio from YouTube")
    @app_commands.describe(query="YouTube URL or search keywords")
    async def play_slash(self, interaction: discord.Interaction, query: str):
        """Play a YouTube track in your voice channel."""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return

        unavailable_reason = self.get_music_unavailable_reason()
        if unavailable_reason:
            await interaction.response.send_message(unavailable_reason, ephemeral=True)
            return

        ffmpeg_path = self.get_ffmpeg_executable()
        await interaction.response.defer(thinking=True)

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        for attempt in range(2):
            try:
                voice_client = interaction.guild.voice_client
                if voice_client and voice_client.channel != voice_channel:
                    await voice_client.move_to(voice_channel)
                elif not voice_client:
                    voice_client = await voice_channel.connect(self_deaf=True, reconnect=False, timeout=12.0)
                break
            except discord.errors.ConnectionClosed as error:
                logger.warning("Voice websocket closed while connecting (attempt %s): %s", attempt + 1, error)
                stale = interaction.guild.voice_client
                if stale:
                    try:
                        await stale.disconnect(force=True)
                    except Exception:
                        pass

                if attempt == 1:
                    await interaction.followup.send(
                        "Voice connection failed (Discord code 4006). This is usually a host voice networking issue; try Python 3.11/3.12 and retry.",
                        ephemeral=True,
                    )
                    return
                await asyncio.sleep(1)
            except asyncio.TimeoutError:
                if attempt == 1:
                    await interaction.followup.send(
                        "Voice connection timed out. Please try /play again.",
                        ephemeral=True,
                    )
                    return
                await asyncio.sleep(1)
            except discord.Forbidden:
                await interaction.followup.send(
                    "I do not have permission to join or speak in that voice channel.",
                    ephemeral=True,
                )
                return
            except discord.ClientException:
                await interaction.followup.send("Could not connect to that voice channel.", ephemeral=True)
                return
            except Exception as error:
                logger.error("Unexpected voice connection error: %s", error)
                await interaction.followup.send("Unexpected error while connecting to voice.", ephemeral=True)
                return

        try:
            track = await self.extract_track(query)
        except RuntimeError as error:
            logger.error("yt-dlp extraction failed: %s", error)
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception as error:
            logger.error("yt-dlp extraction failed: %s", error)
            await interaction.followup.send("Could not load that YouTube track.", ephemeral=True)
            return

        if not track:
            await interaction.followup.send("No playable result found for that query.", ephemeral=True)
            return

        track.requested_by_id = interaction.user.id
        self.text_channels[interaction.guild.id] = interaction.channel_id

        queue = self.queues.setdefault(interaction.guild.id, [])

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            queue.append(track)
            embed = discord.Embed(
                title="Queued",
                description=f"[{track.title}]({track.webpage_url})",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Position", value=str(len(queue)), inline=True)
            embed.add_field(name="Duration", value=format_duration(track.duration), inline=True)
            await interaction.followup.send(embed=embed)
            return

        await self.start_track(interaction.guild, track)
        await interaction.followup.send(f"Loading: {track.title}")

    @app_commands.command(name="skip", description="Skip the current track")
    async def skip_slash(self, interaction: discord.Interaction):
        """Skip current audio and play the next queued track."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected() or not voice_client.is_playing():
            await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)
            return

        voice_client.stop()
        await interaction.response.send_message("Skipped.")

    @app_commands.command(name="stop", description="Stop music and clear the queue")
    async def stop_slash(self, interaction: discord.Interaction):
        """Stop playback, clear queue, and disconnect from voice."""
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        self.queues[guild_id] = []
        self.now_playing.pop(guild_id, None)

        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message("I am not connected to a voice channel.", ephemeral=True)
            return

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        await voice_client.disconnect(force=True)
        await interaction.response.send_message("Stopped playback and disconnected.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
