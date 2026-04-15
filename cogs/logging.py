import json
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class BotLogging(commands.Cog):
    """Chat and server logging with configurable channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config_file = Path(__file__).resolve().parent.parent / 'config.json'
        self.config = {}
        self._load_config()
        self._ensure_logging_config()

    def _load_config(self):
        with self.config_file.open('r', encoding='utf-8') as f:
            self.config = json.load(f)

    def _save_config(self):
        with self.config_file.open('w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2)

    def _ensure_logging_config(self):
        changed = False
        if 'logging_channels' not in self.config:
            self.config['logging_channels'] = {}
            changed = True

        logging_channels = self.config['logging_channels']
        if 'chat_channel' not in logging_channels:
            logging_channels['chat_channel'] = None
            changed = True
        if 'server_channel' not in logging_channels:
            logging_channels['server_channel'] = None
            changed = True
        if 'leave_ping_role' not in logging_channels:
            logging_channels['leave_ping_role'] = None
            changed = True

        if changed:
            self._save_config()

    def _truncate(self, value: str, limit: int = 1024) -> str:
        if not value:
            return 'No content'
        if len(value) <= limit:
            return value
        return value[: limit - 3] + '...'

    def _style_embed(self, embed: discord.Embed, icon: str):
        embed.set_footer(text=f'{icon} Royal Family Logs')
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        return embed

    def _member_label(self, member: discord.abc.User) -> str:
        badge = ' [BOT]' if getattr(member, 'bot', False) else ''
        return f'{member.mention} ({member} | {member.id}){badge}'

    def _person_type(self, user: discord.abc.User) -> str:
        return 'Bot 🤖' if getattr(user, 'bot', False) else 'Human 👤'

    def _person_details(self, user: discord.abc.User) -> str:
        lines = [
            f'• Mention: {user.mention}',
            f'• Display: {getattr(user, "display_name", str(user))}',
            f'• Username: {user}',
            f'• ID: {user.id}',
            f'• Type: {self._person_type(user)}',
        ]

        created_at = getattr(user, 'created_at', None)
        if created_at:
            lines.append(f'• Created: {discord.utils.format_dt(created_at, style="R")}')

        return '\n'.join(lines)

    def _set_person_block(self, embed: discord.Embed, user: discord.abc.User, field_name: str = '👤 Person'):
        embed.add_field(name=field_name, value=self._truncate(self._person_details(user), 1024), inline=False)
        avatar = getattr(user, 'display_avatar', None)
        if avatar:
            embed.set_author(name=f'{user}', icon_url=avatar.url)
        return embed

    def _attachment_lines(self, attachments: list[discord.Attachment]) -> str:
        if not attachments:
            return 'None'
        return '\n'.join(
            f'- [{attachment.filename}]({attachment.url}) ({attachment.content_type or "unknown"})'
            for attachment in attachments
        )

    def _first_image_url(self, attachments: list[discord.Attachment]) -> Optional[str]:
        for attachment in attachments:
            ctype = (attachment.content_type or '').lower()
            if ctype.startswith('image/'):
                return attachment.url
        return None

    def _get_log_channel(self, guild: discord.Guild, key: str) -> Optional[discord.TextChannel]:
        self._load_config()
        self._ensure_logging_config()

        channel_id = self.config.get('logging_channels', {}).get(key)
        if not channel_id:
            return None

        channel = guild.get_channel(channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            return channel
        return None

    async def _send_embed(self, channel: Optional[discord.TextChannel], embed: discord.Embed, content: Optional[str] = None):
        if not channel:
            return

        me = channel.guild.me or channel.guild.get_member(self.bot.user.id)
        if not me or not channel.permissions_for(me).send_messages:
            return

        try:
            allowed_mentions = discord.AllowedMentions(roles=True) if content else None
            await channel.send(content=content, embed=embed, allowed_mentions=allowed_mentions)
        except Exception as e:
            logger.error('Failed to send log embed in %s: %s', channel.id, e)

    @app_commands.command(name='set_chat_log_channel', description='Set the channel used for message edit/delete logs')
    @app_commands.describe(channel='Channel for chat logs')
    @app_commands.checks.has_permissions(administrator=True)
    async def set_chat_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self._load_config()
        self._ensure_logging_config()
        self.config['logging_channels']['chat_channel'] = channel.id
        self._save_config()
        await interaction.response.send_message(f'Chat log channel set to {channel.mention}.', ephemeral=True)

    @app_commands.command(name='set_server_log_channel', description='Set the channel used for join/leave/role/server logs')
    @app_commands.describe(channel='Channel for server logs')
    @app_commands.checks.has_permissions(administrator=True)
    async def set_server_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self._load_config()
        self._ensure_logging_config()
        self.config['logging_channels']['server_channel'] = channel.id
        self._save_config()
        await interaction.response.send_message(f'Server log channel set to {channel.mention}.', ephemeral=True)

    @app_commands.command(name='set_leave_log_ping_role', description='Set the role to ping when someone leaves the server')
    @app_commands.describe(role='Role to ping on member leave logs')
    @app_commands.checks.has_permissions(administrator=True)
    async def set_leave_log_ping_role(self, interaction: discord.Interaction, role: discord.Role):
        self._load_config()
        self._ensure_logging_config()
        self.config['logging_channels']['leave_ping_role'] = role.id
        self._save_config()
        await interaction.response.send_message(f'Leave log ping role set to {role.mention}.', ephemeral=True)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild:
            return
        if before.author == self.bot.user:
            return
        if before.content == after.content and before.attachments == after.attachments:
            return

        channel = self._get_log_channel(before.guild, 'chat_channel')
        embed = self._style_embed(discord.Embed(
            title='✏️ Message Edited',
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        ), '✏️')
        self._set_person_block(embed, before.author, '👤 Author')
        embed.add_field(name='📍 Channel', value=before.channel.mention, inline=True)
        embed.add_field(name='🆔 Message ID', value=str(before.id), inline=True)
        embed.add_field(name='📝 Before', value=self._truncate(before.content or 'No content'), inline=False)
        embed.add_field(name='✅ After', value=self._truncate(after.content or 'No content'), inline=False)

        if before.attachments or after.attachments:
            embed.add_field(
                name='📎 Attachments Before',
                value=self._truncate(self._attachment_lines(before.attachments), 1024),
                inline=False,
            )
            embed.add_field(
                name='🖼️ Attachments After',
                value=self._truncate(self._attachment_lines(after.attachments), 1024),
                inline=False,
            )

            image_url = self._first_image_url(after.attachments) or self._first_image_url(before.attachments)
            if image_url:
                embed.set_image(url=image_url)

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild:
            return
        if message.author == self.bot.user:
            return

        channel = self._get_log_channel(message.guild, 'chat_channel')
        embed = self._style_embed(discord.Embed(
            title='🗑️ Message Deleted',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '🗑️')
        self._set_person_block(embed, message.author, '👤 Author')
        embed.add_field(name='📍 Channel', value=message.channel.mention, inline=True)
        embed.add_field(name='🆔 Message ID', value=str(message.id), inline=True)
        embed.add_field(name='💬 Content', value=self._truncate(message.content or 'No content'), inline=False)
        embed.add_field(
            name='📎 Attachments',
            value=self._truncate(self._attachment_lines(message.attachments), 1024),
            inline=False,
        )

        image_url = self._first_image_url(message.attachments)
        if image_url:
            embed.set_image(url=image_url)

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel = self._get_log_channel(member.guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='✅ Member Joined',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '✅')
        self._set_person_block(embed, member, '👤 Member')
        embed.add_field(name='📅 Account Created', value=discord.utils.format_dt(member.created_at, style='R'), inline=True)
        embed.add_field(name='👥 Member Count', value=str(member.guild.member_count), inline=True)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel = self._get_log_channel(member.guild, 'server_channel')
        self._load_config()
        leave_ping_role_id = self.config.get('logging_channels', {}).get('leave_ping_role')
        leave_ping_role = member.guild.get_role(leave_ping_role_id) if leave_ping_role_id else None
        roster_role_ids = set(self.config.get('roster', {}).get('roles', []))
        member_role_ids = {role.id for role in member.roles}
        should_ping = bool(roster_role_ids & member_role_ids)
        embed = self._style_embed(discord.Embed(
            title='👋 Member Left',
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        ), '👋')
        self._set_person_block(embed, member, '👤 Member')
        embed.add_field(name='👥 Member Count', value=str(member.guild.member_count), inline=True)
        content = leave_ping_role.mention if leave_ping_role and should_ping else None
        await self._send_embed(channel, embed, content=content)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return

        channel = self._get_log_channel(after.guild, 'server_channel')
        before_ids = {role.id for role in before.roles}
        after_ids = {role.id for role in after.roles}

        added = [after.guild.get_role(role_id) for role_id in (after_ids - before_ids)]
        removed = [after.guild.get_role(role_id) for role_id in (before_ids - after_ids)]
        added = [role for role in added if role is not None]
        removed = [role for role in removed if role is not None]

        embed = self._style_embed(discord.Embed(
            title='🎭 Member Roles Updated',
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        ), '🎭')
        self._set_person_block(embed, after, '👤 Member')
        if added:
            embed.add_field(name='➕ Roles Added', value='\n'.join(role.mention for role in added), inline=False)
        if removed:
            embed.add_field(name='➖ Roles Removed', value='\n'.join(role.mention for role in removed), inline=False)

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User):
        channel = self._get_log_channel(guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='⛔ User Banned',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '⛔')
        self._set_person_block(embed, user, '👤 User')
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.abc.User):
        channel = self._get_log_channel(guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='🔓 User Unbanned',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🔓')
        self._set_person_block(embed, user, '👤 User')
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel_obj: discord.abc.GuildChannel):
        channel = self._get_log_channel(channel_obj.guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='🆕 Channel Created',
            description=f'{channel_obj.mention if hasattr(channel_obj, "mention") else channel_obj.name} ({channel_obj.id})',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🆕')
        embed.add_field(name='📂 Type', value=str(channel_obj.type), inline=True)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel_obj: discord.abc.GuildChannel):
        channel = self._get_log_channel(channel_obj.guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='❌ Channel Deleted',
            description=f'{channel_obj.name} ({channel_obj.id})',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '❌')
        embed.add_field(name='📂 Type', value=str(channel_obj.type), inline=True)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        channel = self._get_log_channel(role.guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='🛡️ Role Created',
            description=f'{role.mention} ({role.id})',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🛡️')
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        channel = self._get_log_channel(role.guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='🧹 Role Deleted',
            description=f'{role.name} ({role.id})',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '🧹')
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if before.name == after.name and before.permissions == after.permissions and before.color == after.color:
            return

        channel = self._get_log_channel(after.guild, 'server_channel')
        embed = self._style_embed(discord.Embed(
            title='🛠️ Role Updated',
            description=f'{after.mention} ({after.id})',
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        ), '🛠️')
        if before.name != after.name:
            embed.add_field(name='🏷️ Name', value=f'{before.name} -> {after.name}', inline=False)
        if before.color != after.color:
            embed.add_field(name='🎨 Color', value=f'{before.color} -> {after.color}', inline=False)
        if before.permissions != after.permissions:
            embed.add_field(name='🔐 Permissions', value='Permissions were changed.', inline=False)

        await self._send_embed(channel, embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BotLogging(bot))