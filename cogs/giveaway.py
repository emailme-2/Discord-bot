import asyncio
import json
import logging
import random
import re
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


def parse_duration(duration: str) -> int:
    """Parse duration strings like 30s, 10m, 2h, 1d into seconds."""
    value = duration.strip().lower()
    match = re.fullmatch(r'(\d+)\s*([smhd])', value)
    if not match:
        raise ValueError('Invalid duration format')

    amount = int(match.group(1))
    unit = match.group(2)
    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
    }
    seconds = amount * multipliers[unit]

    if seconds < 10:
        raise ValueError('Duration must be at least 10 seconds')
    if seconds > 30 * 86400:
        raise ValueError('Duration cannot be more than 30 days')
    return seconds


def format_duration(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f'{days}d')
    if hours:
        parts.append(f'{hours}h')
    if minutes:
        parts.append(f'{minutes}m')
    if secs and not parts:
        parts.append(f'{secs}s')
    return ' '.join(parts)


class _GiveawayJoinButton(discord.ui.Button):
    """Button subclass with an explicit custom_id so it survives bot restarts."""

    def __init__(self, cog: 'Giveaway', giveaway_id: int):
        super().__init__(
            label='Enter Giveaway',
            style=discord.ButtonStyle.success,
            emoji='🎉',
            custom_id=f'giveaway_join_{giveaway_id}',
        )
        self._cog = cog
        self._giveaway_id = giveaway_id

    async def callback(self, interaction: discord.Interaction):
        giveaway = self._cog.active_giveaways.get(self._giveaway_id)
        if not giveaway:
            await interaction.response.send_message('This giveaway has already ended.', ephemeral=True)
            return

        if interaction.user.bot:
            await interaction.response.send_message('Bots cannot enter giveaways.', ephemeral=True)
            return

        entrants = giveaway['entrants']
        if interaction.user.id in entrants:
            await interaction.response.send_message(
                "🎟️ You're already in this giveaway! Good luck!", ephemeral=True
            )
            return

        entrants.add(interaction.user.id)
        self._cog._save_active_giveaways()
        await interaction.response.send_message('🎉 You are entered! Good luck!', ephemeral=True)
        await self._cog._refresh_giveaway_entries(self._giveaway_id)


class GiveawayJoinView(discord.ui.View):
    def __init__(self, cog: 'Giveaway', giveaway_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id
        self.add_item(_GiveawayJoinButton(cog, giveaway_id))


class Giveaway(commands.Cog):
    """Giveaway commands and event handling."""

    GIVEAWAYS_FILE = Path(__file__).resolve().parent.parent / 'giveaways.json'
    ACTIVE_GIVEAWAYS_FILE = Path(__file__).resolve().parent.parent / 'active_giveaways.json'

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_giveaways: dict[int, dict] = {}
        self.ended_giveaways: dict[int, dict] = {}
        self._restored = False
        self._load_ended_giveaways()

    @commands.Cog.listener()
    async def on_ready(self):
        if self._restored:
            return
        self._restored = True
        await self._restore_active_giveaways()

    def _load_ended_giveaways(self):
        if not self.GIVEAWAYS_FILE.exists():
            return
        try:
            with self.GIVEAWAYS_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
            for key, value in data.items():
                self.ended_giveaways[int(key)] = value
            logger.info('Loaded %d ended giveaway(s) from disk.', len(data))
        except Exception as e:
            logger.error('Failed to load giveaways.json: %s', e)

    def _save_ended_giveaways(self):
        try:
            serializable = {}
            for key, value in self.ended_giveaways.items():
                serializable[str(key)] = {
                    'message_id': value['message_id'],
                    'channel_id': value['channel_id'],
                    'guild_id': value['guild_id'],
                    'name': value['name'],
                    'host_id': value['host_id'],
                    'winners_count': value['winners_count'],
                    'entrant_ids': value['entrant_ids'],
                    'last_winner_ids': value['last_winner_ids'],
                }
            with self.GIVEAWAYS_FILE.open('w', encoding='utf-8') as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            logger.error('Failed to save giveaways.json: %s', e)

    def _save_active_giveaways(self):
        try:
            serializable = {}
            for key, value in self.active_giveaways.items():
                serializable[str(key)] = {
                    'message_id': key,
                    'channel_id': value['channel'].id,
                    'guild_id': value['guild'].id,
                    'name': value['name'],
                    'host_id': value['host'].id if value['host'] else 0,
                    'winners_count': value['winners_count'],
                    'end_timestamp': value['end_timestamp'],
                    'entrant_ids': list(value['entrants']),
                }
            with self.ACTIVE_GIVEAWAYS_FILE.open('w', encoding='utf-8') as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            logger.error('Failed to save active_giveaways.json: %s', e)

    async def _restore_active_giveaways(self):
        if not self.ACTIVE_GIVEAWAYS_FILE.exists():
            return
        try:
            with self.ACTIVE_GIVEAWAYS_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            logger.error('Failed to load active_giveaways.json: %s', e)
            return

        now = discord.utils.utcnow().timestamp()
        restored = 0

        for key_str, saved in data.items():
            giveaway_id = int(key_str)
            guild = self.bot.get_guild(saved['guild_id'])
            if not guild:
                continue
            channel = self.bot.get_channel(saved['channel_id'])
            if not channel:
                continue
            try:
                message = await channel.fetch_message(giveaway_id)
            except Exception:
                continue

            host = guild.get_member(saved['host_id']) or self.bot.get_user(saved['host_id'])
            remaining = max(0.0, saved['end_timestamp'] - now)

            view = GiveawayJoinView(self, giveaway_id)
            self.bot.add_view(view, message_id=giveaway_id)

            self.active_giveaways[giveaway_id] = {
                'message': message,
                'channel': channel,
                'guild': guild,
                'name': saved['name'],
                'host': host,
                'winners_count': saved['winners_count'],
                'duration': remaining,
                'end_timestamp': saved['end_timestamp'],
                'entrants': set(saved['entrant_ids']),
            }

            self.bot.loop.create_task(self._finish_giveaway(giveaway_id))
            restored += 1

        if restored:
            logger.info('Restored %d active giveaway(s) from disk.', restored)

    def _resolve_entrants(self, guild: discord.Guild, entrant_ids: list[int]) -> list[discord.Member]:
        entrants = []
        for user_id in entrant_ids:
            member = guild.get_member(user_id)
            if member and not member.bot:
                entrants.append(member)
        return entrants

    def _build_giveaway_embed(
        self,
        name: str,
        host: discord.abc.User,
        winners: int,
        duration_seconds: int,
    ) -> discord.Embed:
        end_time = discord.utils.utcnow().timestamp() + duration_seconds
        embed = discord.Embed(
            title=f'🎉 {name} 🎉',
            description=(
                '✨ **A new giveaway just dropped!**\n\n'
                'Click the button below to enter.\n'
                'Winner(s) will be picked automatically.'
            ),
            color=discord.Color.fuchsia(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name='🏆 Winners', value=str(winners), inline=True)
        embed.add_field(name='⏳ Duration', value=format_duration(duration_seconds), inline=True)
        embed.add_field(name='🕒 Ends', value=f'<t:{int(end_time)}:R>', inline=True)
        embed.add_field(name='🎟️ Entries', value='0', inline=True)
        embed.add_field(name='🎮 Hosted By', value=host.mention, inline=True)
        embed.add_field(name='📝 Status', value='Running', inline=True)
        embed.set_footer(text='Royal Family Giveaways • Good luck everyone!')
        return embed

    def _build_end_embed(
        self,
        name: str,
        host: discord.abc.User,
        winners_requested: int,
        winners: list[discord.Member],
        total_entries: int,
    ) -> discord.Embed:
        ended = discord.Embed(
            title=f'🎊 Giveaway Ended: {name}',
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        ended.add_field(name='🎟️ Total Entries', value=str(total_entries), inline=True)
        ended.add_field(name='🏆 Winner Slots', value=str(winners_requested), inline=True)
        ended.add_field(name='🎮 Hosted By', value=host.mention, inline=True)

        if winners:
            ended.add_field(
                name='🥳 Winners',
                value='\n'.join(member.mention for member in winners),
                inline=False,
            )
        else:
            ended.add_field(
                name='😢 Winners',
                value='No valid entries were found for this giveaway.',
                inline=False,
            )

        ended.set_footer(text='Royal Family Giveaways')
        return ended

    def _build_reroll_embed(
        self,
        name: str,
        host: discord.abc.User,
        winners_requested: int,
        winners: list[discord.Member],
        total_entries: int,
    ) -> discord.Embed:
        reroll = discord.Embed(
            title=f'🔁 Giveaway Rerolled: {name}',
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        reroll.add_field(name='🎟️ Total Entries', value=str(total_entries), inline=True)
        reroll.add_field(name='🏆 Winner Slots', value=str(winners_requested), inline=True)
        reroll.add_field(name='🎮 Original Host', value=host.mention, inline=True)

        if winners:
            reroll.add_field(
                name='🥳 New Winners',
                value='\n'.join(member.mention for member in winners),
                inline=False,
            )
        else:
            reroll.add_field(
                name='😢 New Winners',
                value='No valid entries were found for this giveaway.',
                inline=False,
            )

        reroll.set_footer(text='Royal Family Giveaways • Reroll Complete')
        return reroll

    async def _refresh_giveaway_entries(self, giveaway_id: int):
        giveaway = self.active_giveaways.get(giveaway_id)
        if not giveaway:
            return

        message = giveaway['message']
        if not message.embeds:
            return

        embed = message.embeds[0].copy()
        entry_count = len(giveaway['entrants'])

        for index, field in enumerate(embed.fields):
            if field.name == '🎟️ Entries':
                embed.set_field_at(index, name='🎟️ Entries', value=str(entry_count), inline=True)
                break
        else:
            embed.add_field(name='🎟️ Entries', value=str(entry_count), inline=True)

        try:
            await message.edit(embed=embed)
        except Exception as e:
            logger.error('Failed to refresh giveaway entry count for %s: %s', giveaway_id, e)

    async def _finish_giveaway(self, giveaway_id: int):
        giveaway = self.active_giveaways.get(giveaway_id)
        if not giveaway:
            return

        await asyncio.sleep(giveaway['duration'])
        giveaway = self.active_giveaways.pop(giveaway_id, None)
        if not giveaway:
            return
        self._save_active_giveaways()

        message = giveaway['message']
        channel = giveaway['channel']
        guild = giveaway['guild']
        name = giveaway['name']
        host = giveaway['host']
        winners_count = giveaway['winners_count']
        entrant_ids = list(giveaway['entrants'])

        entrants = self._resolve_entrants(guild, entrant_ids)

        picked_count = min(winners_count, len(entrants))
        winners = random.sample(entrants, picked_count) if picked_count > 0 else []

        self.ended_giveaways[giveaway_id] = {
            'message_id': giveaway_id,
            'channel_id': channel.id,
            'guild_id': guild.id,
            'name': name,
            'host_id': host.id,
            'winners_count': winners_count,
            'entrant_ids': entrant_ids,
            'last_winner_ids': [member.id for member in winners],
        }
        self._save_ended_giveaways()

        try:
            disabled_view = GiveawayJoinView(self, giveaway_id)
            for item in disabled_view.children:
                item.disabled = True

            ended_embed = self._build_end_embed(
                name=name,
                host=host,
                winners_requested=winners_count,
                winners=winners,
                total_entries=len(entrants),
            )
            await message.edit(embed=ended_embed, view=disabled_view)

            if winners:
                winner_mentions = ', '.join(member.mention for member in winners)
                await channel.send(f'🎉 Congratulations {winner_mentions}! You won **{name}**!')
            else:
                await channel.send(f'⚠️ Giveaway ended for **{name}**, but there were no valid entries.')
        except Exception as e:
            logger.error('Failed to finalize giveaway %s: %s', giveaway_id, e)

    @app_commands.command(name='giveaway', description='Start a cool giveaway in a selected channel')
    @app_commands.describe(
        channel='Channel to post the giveaway in',
        winners='How many winners to pick',
        duration='Duration like 30s, 10m, 2h, or 1d',
        name='Name of the giveaway prize/event',
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway_slash(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        winners: app_commands.Range[int, 1, 20],
        duration: str,
        name: app_commands.Range[str, 3, 120],
    ):
        try:
            duration_seconds = parse_duration(duration)
        except ValueError:
            await interaction.response.send_message(
                'Invalid duration. Use `30s`, `10m`, `2h`, or `1d`.',
                ephemeral=True,
            )
            return

        me = interaction.guild.me or interaction.guild.get_member(self.bot.user.id)
        if not me or not channel.permissions_for(me).send_messages:
            await interaction.response.send_message(
                f'I cannot send messages in {channel.mention}.',
                ephemeral=True,
            )
            return

        embed = self._build_giveaway_embed(
            name=name,
            host=interaction.user,
            winners=winners,
            duration_seconds=duration_seconds,
        )

        await interaction.response.defer(ephemeral=True)
        message = await channel.send(embed=embed)

        view = GiveawayJoinView(self, message.id)
        await message.edit(view=view)

        self.active_giveaways[message.id] = {
            'message': message,
            'channel': channel,
            'guild': interaction.guild,
            'name': name,
            'host': interaction.user,
            'winners_count': winners,
            'duration': duration_seconds,
            'end_timestamp': discord.utils.utcnow().timestamp() + duration_seconds,
            'entrants': set(),
        }
        self._save_active_giveaways()
        self.bot.loop.create_task(self._finish_giveaway(message.id))

        await interaction.followup.send(
            f'✅ Giveaway started in {channel.mention} for **{name}** with **{winners}** winner(s).',
            ephemeral=True,
        )

    @app_commands.command(name='giveaway_reroll', description='Reroll an ended giveaway by message ID')
    @app_commands.describe(
        giveaway_message_id='The message ID of the giveaway post',
        winners='Optional number of new winners (default uses original winner count)',
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def giveaway_reroll_slash(
        self,
        interaction: discord.Interaction,
        giveaway_message_id: str,
        winners: Optional[app_commands.Range[int, 1, 20]] = None,
    ):
        message_id_text = giveaway_message_id.strip()
        if not message_id_text.isdigit():
            await interaction.response.send_message('Giveaway message ID must be a number.', ephemeral=True)
            return

        message_id = int(message_id_text)
        giveaway = self.ended_giveaways.get(message_id)
        if not giveaway:
            await interaction.response.send_message(
                'No ended giveaway found with that message ID.',
                ephemeral=True,
            )
            return

        guild = self.bot.get_guild(giveaway['guild_id'])
        if not guild or interaction.guild_id != guild.id:
            await interaction.response.send_message('That giveaway belongs to a different server.', ephemeral=True)
            return

        channel = self.bot.get_channel(giveaway['channel_id'])
        if not channel:
            await interaction.response.send_message('The original giveaway channel no longer exists.', ephemeral=True)
            return

        host = guild.get_member(giveaway['host_id']) or self.bot.get_user(giveaway['host_id'])

        entrants = self._resolve_entrants(guild, giveaway['entrant_ids'])
        winners_count = winners if winners is not None else giveaway['winners_count']
        picked_count = min(winners_count, len(entrants))
        new_winners = random.sample(entrants, picked_count) if picked_count > 0 else []

        giveaway['last_winner_ids'] = [member.id for member in new_winners]
        self._save_ended_giveaways()

        reroll_embed = self._build_reroll_embed(
            name=giveaway['name'],
            host=host,
            winners_requested=winners_count,
            winners=new_winners,
            total_entries=len(entrants),
        )

        await interaction.response.defer(ephemeral=True)
        if new_winners:
            winner_mentions = ', '.join(member.mention for member in new_winners)
            await channel.send(
                f'🔁 Reroll complete for **{giveaway["name"]}**! New winner(s): {winner_mentions}',
                embed=reroll_embed,
            )
            await interaction.followup.send('✅ Rerolled giveaway and announced new winner(s).', ephemeral=True)
        else:
            await channel.send(
                f'🔁 Reroll complete for **{giveaway["name"]}**, but there were no valid entries.',
                embed=reroll_embed,
            )
            await interaction.followup.send('⚠️ Reroll done, but no valid entries were available.', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaway(bot))