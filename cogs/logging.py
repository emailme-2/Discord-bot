import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from modules.config import load_config, save_config

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
        self.config = load_config(self.config_file)

    def _save_config(self):
        save_config(self.config_file, self.config)

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

    def _safe_format_dt(self, value) -> str:
        if not value:
            return 'Unknown'
        return discord.utils.format_dt(value, style='R')

    def _style_embed(self, embed: discord.Embed, icon: str):
        embed.set_footer(text=f'{icon} Royal Family Logs')
        if self.bot.user and self.bot.user.display_avatar:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        return embed

    def _member_label(self, member: discord.abc.User) -> str:
        badge = ' [BOT]' if getattr(member, 'bot', False) else ''
        return f'{member.mention} ({member} | {member.id}){badge}'

    def _channel_label(self, channel_obj) -> str:
        mention = getattr(channel_obj, 'mention', None)
        if mention:
            return f'{mention} ({channel_obj.id})'
        return f'{getattr(channel_obj, "name", "Unknown channel")} ({getattr(channel_obj, "id", "Unknown")})'

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

    def _resolve_audit_action(self, name: str) -> Optional[discord.AuditLogAction]:
        return getattr(discord.AuditLogAction, name, None)

    def _has_audit_log_access(self, guild: discord.Guild) -> bool:
        if not self.bot.user:
            return False
        me = guild.me or guild.get_member(self.bot.user.id)
        return bool(me and me.guild_permissions.view_audit_log)

    async def _find_audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        *,
        target_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        limit: int = 6,
        max_age_seconds: int = 15,
    ) -> Optional[discord.AuditLogEntry]:
        if not self._has_audit_log_access(guild):
            return None

        try:
            async for entry in guild.audit_logs(limit=limit, action=action):
                age_seconds = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age_seconds > max_age_seconds:
                    break

                if target_id is not None and getattr(entry.target, 'id', None) != target_id:
                    continue

                if channel_id is not None:
                    extra_channel = getattr(getattr(entry, 'extra', None), 'channel', None)
                    if getattr(extra_channel, 'id', None) != channel_id:
                        continue

                return entry
        except discord.Forbidden:
            return None
        except Exception as error:
            logger.warning('Failed to fetch audit log entry for guild %s: %s', guild.id, error)
        return None

    async def _find_optional_audit_entry(
        self,
        guild: discord.Guild,
        action_name: str,
        **kwargs,
    ) -> Optional[discord.AuditLogEntry]:
        action = self._resolve_audit_action(action_name)
        if action is None:
            return None
        return await self._find_audit_entry(guild, action, **kwargs)

    async def _find_message_delete_audit_entry(
        self,
        guild: discord.Guild,
        *,
        channel_id: int,
        target_id: Optional[int] = None,
        attempts: int = 3,
        delay_seconds: float = 0.75,
    ) -> Optional[discord.AuditLogEntry]:
        for attempt in range(attempts):
            entry = await self._find_audit_entry(
                guild,
                discord.AuditLogAction.message_delete,
                target_id=target_id,
                channel_id=channel_id,
                limit=12,
                max_age_seconds=20,
            )
            if entry:
                return entry

            if attempt < attempts - 1:
                await asyncio.sleep(delay_seconds)

        return None

    async def _find_bulk_message_delete_audit_entry(
        self,
        guild: discord.Guild,
        *,
        channel_id: int,
        deleted_count: Optional[int] = None,
        attempts: int = 3,
        delay_seconds: float = 0.75,
    ) -> Optional[discord.AuditLogEntry]:
        for attempt in range(attempts):
            entry = await self._find_audit_entry(
                guild,
                discord.AuditLogAction.message_bulk_delete,
                channel_id=channel_id,
                limit=12,
                max_age_seconds=20,
            )
            if entry:
                audit_count = getattr(getattr(entry, 'extra', None), 'count', None)
                if deleted_count is None or audit_count is None or audit_count >= deleted_count:
                    return entry

            if attempt < attempts - 1:
                await asyncio.sleep(delay_seconds)

        return None

    def _message_delete_actor_label(self, entry: Optional[discord.AuditLogEntry], *, raw: bool = False) -> str:
        if entry and entry.user:
            return self._member_label(entry.user)
        if raw:
            return 'Unknown (message not cached and no matching audit log entry found)'
        return 'Self-deleted or unknown (no matching audit log entry found)'

    def _add_audit_fields(
        self,
        embed: discord.Embed,
        entry: Optional[discord.AuditLogEntry],
        *,
        actor_name: str = '🛠️ Action By',
    ) -> None:
        if not entry:
            return

        if entry.user:
            embed.add_field(name=actor_name, value=self._truncate(self._member_label(entry.user), 1024), inline=False)

        if entry.reason:
            embed.add_field(name='📝 Reason', value=self._truncate(entry.reason), inline=False)

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
        audit_entry = await self._find_message_delete_audit_entry(
            message.guild,
            target_id=message.author.id,
            channel_id=message.channel.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🗑️ Message Deleted',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '🗑️')
        self._set_person_block(embed, message.author, '👤 Author')
        embed.add_field(name='📍 Channel', value=message.channel.mention, inline=True)
        embed.add_field(name='🆔 Message ID', value=str(message.id), inline=True)
        embed.add_field(name='🕒 Sent', value=self._safe_format_dt(message.created_at), inline=True)

        if audit_entry:
            delete_count = getattr(getattr(audit_entry, 'extra', None), 'count', None)
            embed.add_field(name='🗑️ Deleted By', value=self._message_delete_actor_label(audit_entry), inline=False)
            if audit_entry.reason:
                embed.add_field(name='📝 Reason', value=self._truncate(audit_entry.reason), inline=False)
            if delete_count is not None:
                embed.add_field(name='📊 Recent Deletes By Moderator', value=str(delete_count), inline=True)
        else:
            embed.add_field(name='🗑️ Deleted By', value=self._message_delete_actor_label(audit_entry), inline=False)

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
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        if not messages:
            return

        first_message = messages[0]
        if not first_message.guild:
            return

        channel = self._get_log_channel(first_message.guild, 'chat_channel')
        audit_entry = await self._find_bulk_message_delete_audit_entry(
            first_message.guild,
            channel_id=first_message.channel.id,
            deleted_count=len(messages),
        )

        samples = []
        for message in messages[:5]:
            author = getattr(message, 'author', None)
            author_name = str(author) if author else 'Unknown author'
            content = message.content or '[attachments only]'
            samples.append(f'- {author_name}: {self._truncate(content, 120)}')

        embed = self._style_embed(discord.Embed(
            title='🧨 Bulk Message Delete',
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        ), '🧨')
        embed.add_field(name='📍 Channel', value=self._channel_label(first_message.channel), inline=False)
        embed.add_field(name='🧮 Messages Removed', value=str(len(messages)), inline=True)
        embed.add_field(name='🧾 Sample', value=self._truncate('\n'.join(samples) or 'No cached messages available'), inline=False)
        self._add_audit_fields(embed, audit_entry, actor_name='🗑️ Deleted By')

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if not payload.guild_id or payload.cached_message is not None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = self._get_log_channel(guild, 'chat_channel')
        audit_entry = await self._find_message_delete_audit_entry(
            guild,
            channel_id=payload.channel_id,
        )

        source_channel = guild.get_channel(payload.channel_id)
        channel_label = self._channel_label(source_channel) if source_channel else f'Unknown channel ({payload.channel_id})'
        embed = self._style_embed(discord.Embed(
            title='🗑️ Message Deleted (Uncached)',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '🗑️')
        embed.add_field(name='📍 Channel', value=channel_label, inline=False)
        embed.add_field(name='🆔 Message ID', value=str(payload.message_id), inline=True)
        embed.add_field(name='💬 Content', value='Message was not cached, so content is unavailable.', inline=False)
        embed.add_field(name='🗑️ Deleted By', value=self._message_delete_actor_label(audit_entry, raw=True), inline=False)
        if audit_entry and audit_entry.reason:
            embed.add_field(name='📝 Reason', value=self._truncate(audit_entry.reason), inline=False)

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = self._get_log_channel(guild, 'chat_channel')
        audit_entry = await self._find_bulk_message_delete_audit_entry(
            guild,
            channel_id=payload.channel_id,
            deleted_count=len(payload.message_ids),
        )

        source_channel = guild.get_channel(payload.channel_id)
        channel_label = self._channel_label(source_channel) if source_channel else f'Unknown channel ({payload.channel_id})'
        embed = self._style_embed(discord.Embed(
            title='🧨 Bulk Message Delete (Uncached)',
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        ), '🧨')
        embed.add_field(name='📍 Channel', value=channel_label, inline=False)
        embed.add_field(name='🧮 Messages Removed', value=str(len(payload.message_ids)), inline=True)
        embed.add_field(name='🆔 Message IDs', value=self._truncate(', '.join(str(message_id) for message_id in list(payload.message_ids)[:15]) or 'Unknown'), inline=False)
        embed.add_field(name='🗑️ Deleted By', value=self._message_delete_actor_label(audit_entry, raw=True), inline=False)
        if audit_entry and audit_entry.reason:
            embed.add_field(name='📝 Reason', value=self._truncate(audit_entry.reason), inline=False)

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
        audit_entry = await self._find_audit_entry(
            member.guild,
            discord.AuditLogAction.kick,
            target_id=member.id,
        )
        leave_ping_role_id = self.config.get('logging_channels', {}).get('leave_ping_role')
        leave_ping_role = member.guild.get_role(leave_ping_role_id) if leave_ping_role_id else None
        roster_role_ids = set(self.config.get('roster', {}).get('roles', []))
        member_role_ids = {role.id for role in member.roles}
        should_ping = bool(roster_role_ids & member_role_ids)
        embed = self._style_embed(discord.Embed(
            title='🥾 Member Kicked' if audit_entry else '👋 Member Left',
            color=discord.Color.red() if audit_entry else discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        ), '🥾' if audit_entry else '👋')
        self._set_person_block(embed, member, '👤 Member')
        embed.add_field(name='👥 Member Count', value=str(member.guild.member_count), inline=True)
        self._add_audit_fields(embed, audit_entry, actor_name='🥾 Kicked By')
        content = leave_ping_role.mention if leave_ping_role and should_ping else None
        await self._send_embed(channel, embed, content=content)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        roles_changed = before.roles != after.roles
        nickname_changed = before.nick != after.nick
        timeout_changed = before.communication_disabled_until != after.communication_disabled_until

        if not roles_changed and not nickname_changed and not timeout_changed:
            return

        channel = self._get_log_channel(after.guild, 'server_channel')
        audit_entry = await self._find_audit_entry(
            after.guild,
            discord.AuditLogAction.member_update,
            target_id=after.id,
        )
        before_ids = {role.id for role in before.roles}
        after_ids = {role.id for role in after.roles}

        added = [after.guild.get_role(role_id) for role_id in (after_ids - before_ids)]
        removed = [after.guild.get_role(role_id) for role_id in (before_ids - after_ids)]
        added = [role for role in added if role is not None]
        removed = [role for role in removed if role is not None]

        title = '🎭 Member Roles Updated'
        if nickname_changed and not roles_changed and not timeout_changed:
            title = '🏷️ Nickname Updated'
        elif timeout_changed and not roles_changed and not nickname_changed:
            title = '⏱️ Timeout Updated'

        embed = self._style_embed(discord.Embed(
            title=title,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        ), '🎭')
        self._set_person_block(embed, after, '👤 Member')
        if added:
            embed.add_field(name='➕ Roles Added', value='\n'.join(role.mention for role in added), inline=False)
        if removed:
            embed.add_field(name='➖ Roles Removed', value='\n'.join(role.mention for role in removed), inline=False)

        if nickname_changed:
            embed.add_field(name='🏷️ Nickname', value=f'{before.display_name} -> {after.display_name}', inline=False)

        if timeout_changed:
            before_timeout = self._safe_format_dt(before.communication_disabled_until)
            after_timeout = self._safe_format_dt(after.communication_disabled_until)
            embed.add_field(name='⏱️ Timeout', value=f'{before_timeout} -> {after_timeout}', inline=False)

        self._add_audit_fields(embed, audit_entry)

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.abc.User):
        channel = self._get_log_channel(guild, 'server_channel')
        audit_entry = await self._find_audit_entry(guild, discord.AuditLogAction.ban, target_id=user.id)
        embed = self._style_embed(discord.Embed(
            title='⛔ User Banned',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '⛔')
        self._set_person_block(embed, user, '👤 User')
        self._add_audit_fields(embed, audit_entry, actor_name='🔨 Banned By')
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.abc.User):
        channel = self._get_log_channel(guild, 'server_channel')
        audit_entry = await self._find_audit_entry(guild, discord.AuditLogAction.unban, target_id=user.id)
        embed = self._style_embed(discord.Embed(
            title='🔓 User Unbanned',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🔓')
        self._set_person_block(embed, user, '👤 User')
        self._add_audit_fields(embed, audit_entry, actor_name='🔓 Unbanned By')
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before == after:
            return

        channel = self._get_log_channel(member.guild, 'server_channel')
        if not channel:
            return

        embed = self._style_embed(discord.Embed(
            title='🔊 Voice Activity',
            color=discord.Color.teal(),
            timestamp=discord.utils.utcnow(),
        ), '🔊')
        self._set_person_block(embed, member, '👤 Member')

        changes = []
        audit_entry = None
        actor_name = '🛠️ Action By'
        if before.channel != after.channel:
            if before.channel is None and after.channel is not None:
                embed.title = '🎙️ Voice Channel Joined'
                embed.add_field(name='📢 Joined Channel', value=self._channel_label(after.channel), inline=False)
            elif before.channel is not None and after.channel is None:
                audit_entry = await self._find_optional_audit_entry(
                    member.guild,
                    'member_disconnect',
                    target_id=member.id,
                )
                if audit_entry:
                    embed.title = '🔌 Voice Disconnected (by Moderator)'
                    actor_name = '🔌 Disconnected By'
                else:
                    embed.title = '📤 Voice Channel Left'
                embed.add_field(name='📢 Left Channel', value=self._channel_label(before.channel), inline=False)
            else:
                embed.title = '🔁 Voice Channel Moved'
                embed.add_field(name='📢 From Channel', value=self._channel_label(before.channel), inline=False)
                embed.add_field(name='📢 To Channel', value=self._channel_label(after.channel), inline=False)
                audit_entry = await self._find_optional_audit_entry(
                    member.guild,
                    'member_move',
                    target_id=member.id,
                )
                if audit_entry:
                    actor_name = '🔁 Moved By'

        state_flags = [
            ('Server Mute', before.mute, after.mute),
            ('Server Deaf', before.deaf, after.deaf),
            ('Self Mute', before.self_mute, after.self_mute),
            ('Self Deaf', before.self_deaf, after.self_deaf),
            ('Streaming', before.self_stream, after.self_stream),
            ('Camera', before.self_video, after.self_video),
            ('Suppressed', before.suppress, after.suppress),
            ('AFK', before.afk, after.afk),
        ]

        for label, old_value, new_value in state_flags:
            if old_value != new_value:
                changes.append(f'{label}: {"On" if new_value else "Off"}')

        if before.requested_to_speak_at != after.requested_to_speak_at:
            requested = self._safe_format_dt(after.requested_to_speak_at) if after.requested_to_speak_at else 'Cleared'
            changes.append(f'Request to speak: {requested}')

        if audit_entry is None and any([
            before.mute != after.mute,
            before.deaf != after.deaf,
            before.suppress != after.suppress,
        ]):
            audit_entry = await self._find_optional_audit_entry(
                member.guild,
                'member_update',
                target_id=member.id,
            )

        channel_changed = before.channel != after.channel

        if not changes and not channel_changed:
            return

        if changes:
            embed.add_field(name='🔍 State Changes', value=self._truncate('\n'.join(f'• {change}' for change in changes), 1024), inline=False)
        self._add_audit_fields(embed, audit_entry, actor_name=actor_name)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel_obj: discord.abc.GuildChannel):
        channel = self._get_log_channel(channel_obj.guild, 'server_channel')
        audit_entry = await self._find_audit_entry(
            channel_obj.guild,
            discord.AuditLogAction.channel_create,
            target_id=channel_obj.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🆕 Channel Created',
            description=f'{channel_obj.mention if hasattr(channel_obj, "mention") else channel_obj.name} ({channel_obj.id})',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🆕')
        embed.add_field(name='📂 Type', value=str(channel_obj.type), inline=True)
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel_obj: discord.abc.GuildChannel):
        channel = self._get_log_channel(channel_obj.guild, 'server_channel')
        audit_entry = await self._find_audit_entry(
            channel_obj.guild,
            discord.AuditLogAction.channel_delete,
            target_id=channel_obj.id,
        )
        embed = self._style_embed(discord.Embed(
            title='❌ Channel Deleted',
            description=f'{channel_obj.name} ({channel_obj.id})',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '❌')
        embed.add_field(name='📂 Type', value=str(channel_obj.type), inline=True)
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        changes = []
        if getattr(before, 'name', None) != getattr(after, 'name', None):
            changes.append(f'Name: {before.name} -> {after.name}')
        if getattr(before, 'category', None) != getattr(after, 'category', None):
            before_category = getattr(getattr(before, 'category', None), 'name', None) or 'None'
            after_category = getattr(getattr(after, 'category', None), 'name', None) or 'None'
            changes.append(f'Category: {before_category} -> {after_category}')
        if getattr(before, 'position', None) != getattr(after, 'position', None):
            changes.append(f'Position: {before.position} -> {after.position}')
        if getattr(before, 'topic', None) != getattr(after, 'topic', None):
            changes.append(f'Topic: {getattr(before, "topic", None) or "None"} -> {getattr(after, "topic", None) or "None"}')
        if getattr(before, 'slowmode_delay', None) != getattr(after, 'slowmode_delay', None):
            changes.append(f'Slowmode: {getattr(before, "slowmode_delay", 0)}s -> {getattr(after, "slowmode_delay", 0)}s')
        if getattr(before, 'nsfw', None) != getattr(after, 'nsfw', None):
            changes.append(f'NSFW: {getattr(before, "nsfw", False)} -> {getattr(after, "nsfw", False)}')
        if getattr(before, 'bitrate', None) != getattr(after, 'bitrate', None):
            changes.append(f'Bitrate: {getattr(before, "bitrate", 0)} -> {getattr(after, "bitrate", 0)}')
        if getattr(before, 'user_limit', None) != getattr(after, 'user_limit', None):
            changes.append(f'User Limit: {getattr(before, "user_limit", 0)} -> {getattr(after, "user_limit", 0)}')
        if getattr(before, 'rtc_region', None) != getattr(after, 'rtc_region', None):
            changes.append(f'Region: {getattr(before, "rtc_region", None) or "Auto"} -> {getattr(after, "rtc_region", None) or "Auto"}')

        if not changes:
            return

        channel = self._get_log_channel(after.guild, 'server_channel')
        audit_entry = await self._find_audit_entry(
            after.guild,
            discord.AuditLogAction.channel_update,
            target_id=after.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🛠️ Channel Updated',
            description=self._channel_label(after),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        ), '🛠️')
        embed.add_field(name='🔍 Changes', value=self._truncate('\n'.join(f'• {change}' for change in changes), 1024), inline=False)
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        channel = self._get_log_channel(role.guild, 'server_channel')
        audit_entry = await self._find_audit_entry(
            role.guild,
            discord.AuditLogAction.role_create,
            target_id=role.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🛡️ Role Created',
            description=f'{role.mention} ({role.id})',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🛡️')
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        channel = self._get_log_channel(role.guild, 'server_channel')
        audit_entry = await self._find_audit_entry(
            role.guild,
            discord.AuditLogAction.role_delete,
            target_id=role.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🧹 Role Deleted',
            description=f'{role.name} ({role.id})',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '🧹')
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if before.name == after.name and before.permissions == after.permissions and before.color == after.color:
            return

        channel = self._get_log_channel(after.guild, 'server_channel')
        audit_entry = await self._find_audit_entry(
            after.guild,
            discord.AuditLogAction.role_update,
            target_id=after.id,
        )
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

        self._add_audit_fields(embed, audit_entry)

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = []
        if before.name != after.name:
            changes.append(f'Name: {before.name} -> {after.name}')
        if before.description != after.description:
            changes.append(f'Description: {(before.description or "None")} -> {(after.description or "None")}')
        if before.verification_level != after.verification_level:
            changes.append(f'Verification: {before.verification_level} -> {after.verification_level}')
        if before.afk_timeout != after.afk_timeout:
            changes.append(f'AFK Timeout: {before.afk_timeout}s -> {after.afk_timeout}s')
        if before.afk_channel != after.afk_channel:
            changes.append(f'AFK Channel: {self._channel_label(before.afk_channel) if before.afk_channel else "None"} -> {self._channel_label(after.afk_channel) if after.afk_channel else "None"}')
        if before.system_channel != after.system_channel:
            changes.append(f'System Channel: {self._channel_label(before.system_channel) if before.system_channel else "None"} -> {self._channel_label(after.system_channel) if after.system_channel else "None"}')
        if before.rules_channel != after.rules_channel:
            changes.append(f'Rules Channel: {self._channel_label(before.rules_channel) if before.rules_channel else "None"} -> {self._channel_label(after.rules_channel) if after.rules_channel else "None"}')
        if before.public_updates_channel != after.public_updates_channel:
            changes.append(f'Updates Channel: {self._channel_label(before.public_updates_channel) if before.public_updates_channel else "None"} -> {self._channel_label(after.public_updates_channel) if after.public_updates_channel else "None"}')

        if not changes:
            return

        channel = self._get_log_channel(after, 'server_channel')
        audit_entry = await self._find_audit_entry(after, discord.AuditLogAction.guild_update)
        embed = self._style_embed(discord.Embed(
            title='🏰 Server Updated',
            description=f'{after.name} ({after.id})',
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        ), '🏰')
        embed.add_field(name='🔍 Changes', value=self._truncate('\n'.join(f'• {change}' for change in changes), 1024), inline=False)
        self._add_audit_fields(embed, audit_entry)

        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        channel = self._get_log_channel(thread.guild, 'server_channel')
        audit_entry = await self._find_optional_audit_entry(
            thread.guild,
            'thread_create',
            target_id=thread.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🧵 Thread Created',
            description=f'{thread.mention} ({thread.id})',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🧵')
        embed.add_field(name='📍 Parent', value=self._channel_label(thread.parent) if thread.parent else 'Unknown', inline=False)
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        channel = self._get_log_channel(thread.guild, 'server_channel')
        audit_entry = await self._find_optional_audit_entry(
            thread.guild,
            'thread_delete',
            target_id=thread.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🧵 Thread Deleted',
            description=f'{thread.name} ({thread.id})',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '🧵')
        embed.add_field(name='📍 Parent', value=self._channel_label(thread.parent) if thread.parent else 'Unknown', inline=False)
        self._add_audit_fields(embed, audit_entry, actor_name='🗑️ Deleted By')
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        changes = []
        if before.name != after.name:
            changes.append(f'Name: {before.name} -> {after.name}')
        if before.archived != after.archived:
            changes.append(f'Archived: {before.archived} -> {after.archived}')
        if before.locked != after.locked:
            changes.append(f'Locked: {before.locked} -> {after.locked}')
        if before.slowmode_delay != after.slowmode_delay:
            changes.append(f'Slowmode: {before.slowmode_delay}s -> {after.slowmode_delay}s')
        if before.auto_archive_duration != after.auto_archive_duration:
            changes.append(f'Auto Archive: {before.auto_archive_duration}m -> {after.auto_archive_duration}m')

        if not changes:
            return

        channel = self._get_log_channel(after.guild, 'server_channel')
        audit_entry = await self._find_optional_audit_entry(
            after.guild,
            'thread_update',
            target_id=after.id,
        )
        embed = self._style_embed(discord.Embed(
            title='🧵 Thread Updated',
            description=f'{after.mention} ({after.id})',
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        ), '🧵')
        embed.add_field(name='🔍 Changes', value=self._truncate('\n'.join(f'• {change}' for change in changes), 1024), inline=False)
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        guild = invite.guild
        if guild is None:
            return

        channel = self._get_log_channel(guild, 'server_channel')
        audit_entry = await self._find_optional_audit_entry(guild, 'invite_create')
        embed = self._style_embed(discord.Embed(
            title='🔗 Invite Created',
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        ), '🔗')
        if invite.channel:
            embed.add_field(name='📍 Channel', value=self._channel_label(invite.channel), inline=False)
        embed.add_field(name='🏷️ Code', value=invite.code, inline=True)
        embed.add_field(name='⌛ Max Uses', value=str(invite.max_uses or 'Unlimited'), inline=True)
        embed.add_field(name='🕒 Expires', value=self._safe_format_dt(invite.expires_at) if invite.expires_at else 'Never', inline=True)
        self._add_audit_fields(embed, audit_entry)
        await self._send_embed(channel, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        guild = invite.guild
        if guild is None:
            return

        channel = self._get_log_channel(guild, 'server_channel')
        audit_entry = await self._find_optional_audit_entry(guild, 'invite_delete')
        embed = self._style_embed(discord.Embed(
            title='🔗 Invite Deleted',
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        ), '🔗')
        if invite.channel:
            embed.add_field(name='📍 Channel', value=self._channel_label(invite.channel), inline=False)
        embed.add_field(name='🏷️ Code', value=invite.code, inline=True)
        self._add_audit_fields(embed, audit_entry, actor_name='🗑️ Deleted By')
        await self._send_embed(channel, embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BotLogging(bot))