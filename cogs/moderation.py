import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)

class Moderation(commands.Cog):
    """Moderation commands for the bot"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="The member to kick", reason="Reason for kicking (optional)")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        """Kick a member from the server"""
        await member.kick(reason=reason)
        embed = discord.Embed(
            title="Member Kicked",
            description=f"{member.mention} has been kicked",
            color=discord.Color.red()
        )
        if reason:
            embed.add_field(name="Reason", value=reason)
        await interaction.response.send_message(embed=embed)
        logger.info(f'Kicked {member} from {interaction.guild}. Reason: {reason}')
    
    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="The member to ban", reason="Reason for banning (optional)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        """Ban a member from the server"""
        await member.ban(reason=reason)
        embed = discord.Embed(
            title="Member Banned",
            description=f"{member.mention} has been banned",
            color=discord.Color.red()
        )
        if reason:
            embed.add_field(name="Reason", value=reason)
        await interaction.response.send_message(embed=embed)
        logger.info(f'Banned {member} from {interaction.guild}. Reason: {reason}')
    
    @app_commands.command(name="clear", description="Clear messages from the channel")
    @app_commands.describe(amount="Number of messages to delete (1-100, default 10)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_slash(self, interaction: discord.Interaction, amount: int = 10):
        """Clear messages from the channel"""
        if amount < 1 or amount > 100:
            await interaction.response.send_message("Please specify a number between 1 and 100", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        embed = discord.Embed(
            title="Messages Cleared",
            description=f"Deleted {len(deleted)} messages",
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f'Cleared {len(deleted)} messages in {interaction.channel}')

async def setup(bot):
    """Setup function to load the cog"""
    await bot.add_cog(Moderation(bot))
