import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parent.parent / 'sticky_messages.json'


def _load_data() -> dict:
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open('r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_data(data: dict):
    with DATA_FILE.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


class Sticky(commands.Cog):
    """Keeps a sticky message as the last message in a channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # { channel_id_str: { "text": str, "message_id": int | None } }
        self.sticky: dict[str, dict] = _load_data()
        # Tracks channels currently being reposted to avoid re-triggering
        self._reposting: set[int] = set()

    # ── /pin ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="pin", description="Set a sticky message that always stays last in this channel")
    @app_commands.describe(message="The message to keep pinned at the bottom of the channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def pin(self, interaction: discord.Interaction, message: str):
        channel = interaction.channel
        key = str(channel.id)

        # Delete any existing sticky message in this channel
        existing = self.sticky.get(key)
        if existing and existing.get('message_id'):
            try:
                old_msg = await channel.fetch_message(existing['message_id'])
                await old_msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        await interaction.response.send_message("✅ Sticky message set.", ephemeral=True)

        sent = await channel.send(message)
        self.sticky[key] = {'text': message, 'message_id': sent.id}
        _save_data(self.sticky)
        logger.info("Sticky set in #%s (%s) by %s", channel.name, channel.id, interaction.user)

    # ── /unpin ────────────────────────────────────────────────────────────────
    @app_commands.command(name="unpin", description="Remove the sticky message from this channel")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unpin(self, interaction: discord.Interaction):
        key = str(interaction.channel.id)
        entry = self.sticky.get(key)

        if not entry:
            await interaction.response.send_message("There is no sticky message in this channel.", ephemeral=True)
            return

        if entry.get('message_id'):
            try:
                msg = await interaction.channel.fetch_message(entry['message_id'])
                await msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

        del self.sticky[key]
        _save_data(self.sticky)
        await interaction.response.send_message("✅ Sticky message removed.", ephemeral=True)
        logger.info("Sticky removed from #%s (%s) by %s", interaction.channel.name, interaction.channel.id, interaction.user)

    # ── Listener ──────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore DMs, bots, and channels with no sticky
        if not message.guild or message.author.bot:
            return

        key = str(message.channel.id)
        entry = self.sticky.get(key)
        if not entry:
            return

        channel = message.channel

        # If this message IS the current sticky, do nothing
        if message.id == entry.get('message_id'):
            return

        # Prevent re-triggering while we repost
        if channel.id in self._reposting:
            return
        self._reposting.add(channel.id)

        try:
            # Delete old sticky
            old_id = entry.get('message_id')
            if old_id:
                try:
                    old_msg = await channel.fetch_message(old_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            # Repost sticky
            sent = await channel.send(entry['text'])
            self.sticky[key]['message_id'] = sent.id
            _save_data(self.sticky)
        except Exception as e:
            logger.error("Error reposting sticky in channel %s: %s", channel.id, e)
        finally:
            self._reposting.discard(channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Sticky(bot))
