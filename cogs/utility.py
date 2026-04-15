import platform
import sys
from typing import Optional, Union

import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


def parse_embed_color(raw_value: str) -> Optional[discord.Color]:
    """Parse a user-provided color string into a discord.Color."""
    if not raw_value:
        return discord.Color.gold()

    value = raw_value.strip().lower()
    named_colors = {
        'red': discord.Color.red(),
        'green': discord.Color.green(),
        'blue': discord.Color.blue(),
        'gold': discord.Color.gold(),
        'orange': discord.Color.orange(),
        'purple': discord.Color.purple(),
        'teal': discord.Color.teal(),
        'magenta': discord.Color.magenta(),
        'dark_blue': discord.Color.dark_blue(),
        'dark_green': discord.Color.dark_green(),
    }

    if value in named_colors:
        return named_colors[value]

    hex_value = value.lstrip('#')
    if len(hex_value) == 6:
        try:
            return discord.Color(int(hex_value, 16))
        except ValueError:
            return None

    return None


class AnnouncementModal(discord.ui.Modal, title="Create Announcement"):
    """Modal used to collect announcement embed content."""

    title_input = discord.ui.TextInput(
        label="Title",
        placeholder="Enter announcement title...",
        max_length=256,
        required=True,
    )
    description_input = discord.ui.TextInput(
        label="Description",
        placeholder="Write your announcement details...",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
    )
    color_input = discord.ui.TextInput(
        label="Color (hex or name)",
        placeholder="Examples: #FFD700, gold, red, blue",
        max_length=32,
        required=False,
    )
    footer_input = discord.ui.TextInput(
        label="Footer (optional)",
        placeholder="Footer text for the embed",
        max_length=2048,
        required=False,
    )
    image_input = discord.ui.TextInput(
        label="Image URL (optional)",
        placeholder="https://example.com/image.png",
        max_length=1024,
        required=False,
    )

    def __init__(
        self,
        target_channel: discord.TextChannel,
        mention_content: str,
        requested_by: Union[discord.Member, discord.User],
    ):
        super().__init__()
        self.target_channel = target_channel
        self.mention_content = mention_content
        self.requested_by = requested_by

    async def on_submit(self, interaction: discord.Interaction):
        color = parse_embed_color(str(self.color_input))
        if color is None:
            await interaction.response.send_message(
                "Invalid color. Use a 6-digit hex like #FFD700 or a basic name like gold/red/blue.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=str(self.title_input),
            description=str(self.description_input),
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(
            name=f"Announcement from {self.requested_by.display_name}",
            icon_url=self.requested_by.display_avatar.url,
        )

        footer_text = str(self.footer_input).strip()
        if footer_text:
            embed.set_footer(text=footer_text)

        image_url = str(self.image_input).strip()
        if image_url:
            if image_url.startswith(('http://', 'https://')):
                embed.set_image(url=image_url)
            else:
                await interaction.response.send_message(
                    "Image URL must start with http:// or https://",
                    ephemeral=True,
                )
                return

        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        try:
            sent_message = await self.target_channel.send(
                content=self.mention_content or None,
                embed=embed,
            )
            await interaction.response.send_message(
                f"Announcement sent in {self.target_channel.mention}: {sent_message.jump_url}",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I do not have permission to send messages in that channel.",
                ephemeral=True,
            )
        except discord.HTTPException as error:
            logger.error("Failed to send announcement: %s", error)
            await interaction.response.send_message(
                "Failed to send the announcement due to a Discord API error.",
                ephemeral=True,
            )

class Utility(commands.Cog):
    """Utility commands for the bot"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="ping", description="Check bot latency")
    async def ping_slash(self, interaction: discord.Interaction):
        """Check bot latency"""
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="Pong!",
            description=f"Bot latency: {latency}ms",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="info", description="Get info about the bot and server")
    async def info_slash(self, interaction: discord.Interaction):
        """Get info about the bot and the server"""
        bot_user = self.bot.user
        latency = round(self.bot.latency * 1000)
        guild_count = len(self.bot.guilds)
        total_members = sum(guild.member_count or 0 for guild in self.bot.guilds)
        command_count = len(self.bot.tree.get_commands())

        # Uptime
        start_time = getattr(self.bot, 'start_time', None)
        uptime_str = discord.utils.format_dt(start_time, style='R') if start_time else "Unknown"
        online_since_str = discord.utils.format_dt(start_time, style='F') if start_time else "Unknown"

        # discord.py version
        dpy_version = discord.__version__
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        # ── BOT EMBED ──────────────────────────────────────────────
        bot_embed = discord.Embed(
            title="<:emoji_6:1441736523237294223>  Royal Family Bot  <:emoji_6:1441736523237294223>",
            description="Utility, roster management, logging, moderation, and giveaways — all in one bot built for Royal Family.",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        bot_embed.set_thumbnail(url=bot_user.display_avatar.url)

        bot_embed.add_field(name="🤖 Username", value=str(bot_user), inline=True)
        bot_embed.add_field(name="🆔 Bot ID", value=str(bot_user.id), inline=True)
        bot_embed.add_field(name="⚡ Latency", value=f"{latency}ms", inline=True)

        bot_embed.add_field(name="🌐 Servers", value=str(guild_count), inline=True)
        bot_embed.add_field(name="👥 Total Members", value=str(total_members), inline=True)
        bot_embed.add_field(name="🧩 Slash Commands", value=str(command_count), inline=True)

        bot_embed.add_field(name="📅 Bot Created", value=discord.utils.format_dt(bot_user.created_at, style='F'), inline=False)
        bot_embed.add_field(name="🟢 Online Since", value=f"{online_since_str} ({uptime_str})", inline=False)

        bot_embed.add_field(name="📦 discord.py", value=f"v{dpy_version}", inline=True)
        bot_embed.add_field(name="🐍 Python", value=f"v{py_version}", inline=True)
        bot_embed.add_field(name="💻 Platform", value=platform.system(), inline=True)

        bot_embed.add_field(
            name="⚙️ Features",
            value=(
                "• Roster management & display\n"
                "• Moderation (kick, ban, clear)\n"
                "• Message & server event logging\n"
                "• Welcome messages\n"
                "• Giveaways with reroll support"
            ),
            inline=False
        )
        bot_embed.set_footer(text="Royal Family Bot • /help for all commands")

        # ── SERVER EMBED ───────────────────────────────────────────
        guild = interaction.guild
        if guild:
            # Member breakdown
            humans = sum(1 for m in guild.members if not m.bot)
            bots = sum(1 for m in guild.members if m.bot)

            # Channel breakdown
            text_channels = len(guild.text_channels)
            voice_channels = len(guild.voice_channels)
            categories = len(guild.categories)
            stage_channels = len(guild.stage_channels)
            forum_channels = len(guild.forums)

            # Roles (exclude @everyone)
            role_count = len(guild.roles) - 1

            # Verification level
            verification = str(guild.verification_level).replace('_', ' ').title()

            # Boost info
            boost_level = guild.premium_tier
            boost_count = guild.premium_subscription_count or 0

            # Owner
            owner = guild.owner
            owner_str = f"{owner.mention} ({owner})" if owner else "Unknown"

            # Emoji & sticker counts
            emoji_count = len(guild.emojis)
            sticker_count = len(guild.stickers)

            # Animated emojis
            animated_emojis = sum(1 for e in guild.emojis if e.animated)
            static_emojis = emoji_count - animated_emojis

            server_embed = discord.Embed(
                title=f"🏰 {guild.name}",
                description=guild.description or "No server description set.",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            if guild.icon:
                server_embed.set_thumbnail(url=guild.icon.url)
            if guild.banner:
                server_embed.set_image(url=guild.banner.with_format('png').url)

            server_embed.add_field(name="🆔 Server ID", value=str(guild.id), inline=True)
            server_embed.add_field(name="👑 Owner", value=owner_str, inline=False)
            server_embed.add_field(name="📅 Created", value=discord.utils.format_dt(guild.created_at, style='F'), inline=False)

            server_embed.add_field(
                name=f"👥 Members ({guild.member_count})",
                value=f"👤 Humans: {humans}\n🤖 Bots: {bots}",
                inline=True
            )
            server_embed.add_field(
                name=f"💬 Channels ({text_channels + voice_channels + stage_channels + forum_channels})",
                value=(
                    f"📝 Text: {text_channels}\n"
                    f"🔊 Voice: {voice_channels}\n"
                    f"📁 Categories: {categories}\n"
                    f"🎭 Stage: {stage_channels}\n"
                    f"💬 Forums: {forum_channels}"
                ),
                inline=True
            )
            server_embed.add_field(
                name=f"😀 Emojis ({emoji_count})",
                value=f"Static: {static_emojis} | Animated: {animated_emojis}\nStickers: {sticker_count}",
                inline=True
            )
            server_embed.add_field(name="🎭 Roles", value=str(role_count), inline=True)
            server_embed.add_field(name="🛡️ Verification", value=verification, inline=True)
            server_embed.add_field(
                name=f"🚀 Boosts (Level {boost_level})",
                value=f"{boost_count} boost{'s' if boost_count != 1 else ''}",
                inline=True
            )

            # Notable server features
            notable_features = {
                'COMMUNITY': '🏘️ Community',
                'PARTNERED': '🤝 Partnered',
                'VERIFIED': '✅ Verified',
                'DISCOVERABLE': '🔍 Discoverable',
                'VANITY_URL': '🔗 Vanity URL',
                'ANIMATED_ICON': '🎞️ Animated Icon',
                'BANNER': '🖼️ Banner',
                'INVITE_SPLASH': '💦 Invite Splash',
                'ROLE_ICONS': '🎨 Role Icons',
                'TICKETED_EVENTS_ENABLED': '🎟️ Ticketed Events',
            }
            active = [label for key, label in notable_features.items() if key in guild.features]
            if active:
                server_embed.add_field(name="✨ Server Features", value="  ".join(active), inline=False)

            server_embed.set_footer(text="Royal Family Bot • Server Info")

            await interaction.response.send_message(embeds=[bot_embed, server_embed])
        else:
            await interaction.response.send_message(embed=bot_embed)
    
    @app_commands.command(name="help", description="Show available slash commands")
    async def help_slash(self, interaction: discord.Interaction):
        """Show help for available slash commands"""
        embed = discord.Embed(
            title="Help - Available Slash Commands",
            description="Here are the available slash commands:",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="🏆 Roster Commands",
            value=(
                "`/roster` - Display the server roster\n"
                "`/roster_add` - Add a role to the roster (Admin)\n"
                "`/roster_remove` - Remove a role from the roster (Admin)\n"
                "`/roster_list` - List all roles in the roster\n"
                "`/roster_reorder` - Reorder roster roles (Admin)\n"
                "`/roster_include` - Include a member in roster (Admin)\n"
                "`/roster_exclude` - Exclude a member from roster (Admin)\n"
                "`/roster_name` - Set roster display name (Admin)\n"
                "`/check_reaction` - Show which roster members have not reacted (Admin)"
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Moderation Commands",
            value=(
                "`/kick` - Kick a member from the server (Kick perms)\n"
                "`/ban` - Ban a member from the server (Ban perms)\n"
                "`/clear` - Clear messages from channel (Manage msgs)"
            ),
            inline=False
        )

        embed.add_field(
            name="🔧 Utility Commands",
            value=(
                "`/ping` - Check bot latency\n"
                "`/info` - Get bot information\n"
                "`/help` - Show this help message\n"
                "`/announcement` - Open announcement builder (Manage Server)\n"
                "`/echo` - Echo a message"
            ),
            inline=False
        )

        embed.add_field(
            name="📝 Logging Setup (Admin)",
            value=(
                "`/set_chat_log_channel` - Set channel for message edit/delete logs\n"
                "`/set_server_log_channel` - Set channel for joins, leaves, roles, and server logs\n"
                "`/set_leave_log_ping_role` - Set role to ping when someone leaves"
            ),
            inline=False
        )

        embed.add_field(
            name="🎉 Giveaways (Admin)",
            value=(
                "`/giveaway` - Create a giveaway with channel, winners, duration, and name\n"
                "`/giveaway_reroll` - Reroll an ended giveaway by message ID"
            ),
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="echo", description="Echo a message")
    @app_commands.describe(message="The message to echo")
    async def echo_slash(self, interaction: discord.Interaction, message: str):
        """Echo a message"""
        await interaction.response.send_message(message)

    @app_commands.command(name="announcement", description="Create and send a styled announcement")
    @app_commands.describe(
        channel="Channel to send the announcement",
        ping_everyone="Mention @everyone in the announcement",
        ping_here="Mention @here in the announcement",
        ping_role="Role to mention in the announcement",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def announcement_slash(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        ping_everyone: bool = False,
        ping_here: bool = False,
        ping_role: Optional[discord.Role] = None,
    ):
        """Open a modal to build and post an announcement embed."""
        mention_parts = []
        if ping_everyone:
            mention_parts.append('@everyone')
        if ping_here:
            mention_parts.append('@here')
        if ping_role is not None:
            mention_parts.append(ping_role.mention)

        mention_content = ' '.join(mention_parts)

        perms = channel.permissions_for(interaction.guild.me) if interaction.guild else None
        if perms and (not perms.send_messages or not perms.embed_links):
            await interaction.response.send_message(
                f"I need Send Messages and Embed Links in {channel.mention}.",
                ephemeral=True,
            )
            return

        modal = AnnouncementModal(
            target_channel=channel,
            mention_content=mention_content,
            requested_by=interaction.user,
        )
        await interaction.response.send_modal(modal)

    @announcement_slash.error
    async def announcement_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handle permission errors for announcement command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                "You need Manage Server permission to use this command.",
                ephemeral=True,
            )
            return
        logger.error("Unexpected announcement command error: %s", error)
        if interaction.response.is_done():
            await interaction.followup.send("Something went wrong while opening the announcement form.", ephemeral=True)
        else:
            await interaction.response.send_message("Something went wrong while opening the announcement form.", ephemeral=True)

async def setup(bot):
    """Setup function to load the cog"""
    await bot.add_cog(Utility(bot))
