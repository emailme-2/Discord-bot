import json
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from modules.config import load_config, save_config
from modules.welcome import generate_welcome_image

logger = logging.getLogger(__name__)


class Welcome(commands.Cog):
    """Welcome card and welcome channel commands."""

    def __init__(self, bot):
        self.bot = bot
        self.config_file = Path(__file__).resolve().parent.parent / 'config.json'
        self.load_config()

    def load_config(self):
        self.config = load_config(self.config_file)

    def save_config(self):
        save_config(self.config_file, self.config)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Reload on each join so runtime slash-command config updates are reflected.
        self.load_config()
        welcome_channel_id = self.config['roster'].get('welcome_channel')
        if not welcome_channel_id:
            logger.info('Welcome channel is not configured; skipping welcome for %s', member.display_name)
            return

        channel = member.guild.get_channel(welcome_channel_id)
        if not channel:
            logger.warning('Welcome channel not found: %s', welcome_channel_id)
            return

        me = member.guild.me or member.guild.get_member(self.bot.user.id)
        if not me:
            logger.warning('Could not resolve bot member in guild %s', member.guild.id)
            return

        if not channel.permissions_for(me).send_messages:
            logger.warning('Bot cannot send messages in welcome channel: %s', welcome_channel_id)
            return

        try:
            canvas_path = self.config['roster'].get('welcome_canvas')
            image_buffer = generate_welcome_image(
                member.name,
                member.created_at,
                member.guild.member_count,
                canvas_path,
            )
            file = discord.File(image_buffer, filename='welcome.png')

            embed = discord.Embed(
                title='🎉 Welcome!',
                description=f'{member.mention} has joined **{member.guild.name}**',
                color=discord.Color.gold(),
            )
            embed.set_image(url='attachment://welcome.png')
            embed.set_footer(text='Royal Family Welcome')

            await channel.send(embed=embed, file=file)
            logger.info('Welcome image sent for %s in #%s', member.display_name, channel.name)
        except Exception as e:
            logger.exception('Failed to generate/send welcome image for %s: %s', member.display_name, e)
            await channel.send(f'🎉 Welcome {member.mention} to **{member.guild.name}**!')
            logger.info('Sent fallback text welcome for %s in #%s', member.display_name, channel.name)

    @app_commands.command(name='welcome_setup', description='Set the welcome channel and optional canvas image path')
    @app_commands.describe(channel='Channel for welcome cards', canvas_path='Optional local image path for the welcome canvas')
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_setup(self, interaction: discord.Interaction, channel: discord.TextChannel, canvas_path: Optional[str] = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('You need administrator permissions to use this command.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        self.config['roster']['welcome_channel'] = channel.id
        if canvas_path:
            self.config['roster']['welcome_canvas'] = canvas_path.strip()
        self.save_config()

        message = f'Welcome announcements will now be posted in {channel.mention}.'
        if canvas_path:
            message += f' Canvas image path set to `{canvas_path}`.'

        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(name='welcome_test', description='Send a test welcome card to the configured channel')
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_test(self, interaction: discord.Interaction):
        self.load_config()
        welcome_channel_id = self.config['roster'].get('welcome_channel')
        if not welcome_channel_id:
            await interaction.response.send_message('Welcome channel is not configured. Use `/welcome_setup` first.', ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(welcome_channel_id)
        if not channel:
            await interaction.followup.send(f'Welcome channel with ID {welcome_channel_id} not found.', ephemeral=True)
            return

        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.followup.send(f'I do not have permission to send messages in {channel.mention}.', ephemeral=True)
            return

        canvas_path = self.config['roster'].get('welcome_canvas')
        image_buffer = generate_welcome_image(
            interaction.user.name,
            interaction.user.created_at,
            interaction.guild.member_count,
            canvas_path,
        )
        file = discord.File(image_buffer, filename='welcome.png')

        embed = discord.Embed(
            title='🧪 Welcome Card Test',
            description=f'Testing welcome card for {interaction.user.mention}.',
            color=discord.Color.blue(),
        )
        embed.set_image(url='attachment://welcome.png')
        embed.set_footer(text='Royal Family Welcome Test')

        await channel.send(embed=embed, file=file)
        await interaction.followup.send(f'✅ Test welcome card sent to {channel.mention}.', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
