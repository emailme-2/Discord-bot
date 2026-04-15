import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)

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
    
    @app_commands.command(name="info", description="Get info about the bot")
    async def info_slash(self, interaction: discord.Interaction):
        """Get info about the bot"""
        bot_user = self.bot.user
        latency = round(self.bot.latency * 1000)
        guild_count = len(self.bot.guilds)
        member_count = sum(guild.member_count or 0 for guild in self.bot.guilds)
        command_count = len(self.bot.tree.get_commands())

        embed = discord.Embed(
            title="Royal Family Bot Info",
            description="Utility, roster management, logging, moderation, and giveaways in one bot.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🤖 Bot", value=f"{bot_user.mention}\n{bot_user}", inline=True)
        embed.add_field(name="🆔 Bot ID", value=str(bot_user.id), inline=True)
        embed.add_field(name="⚡ Latency", value=f"{latency}ms", inline=True)
        embed.add_field(name="🌐 Servers", value=str(guild_count), inline=True)
        embed.add_field(name="👥 Users", value=str(member_count), inline=True)
        embed.add_field(name="🧩 Commands", value=str(command_count), inline=True)
        embed.add_field(
            name="📅 Created",
            value=discord.utils.format_dt(bot_user.created_at, style='F'),
            inline=False
        )
        embed.set_thumbnail(url=bot_user.display_avatar.url)
        embed.set_footer(text="Royal Family Bot")
        await interaction.response.send_message(embed=embed)
    
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

async def setup(bot):
    """Setup function to load the cog"""
    await bot.add_cog(Utility(bot))
