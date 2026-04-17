import json
import logging
import os
import sys
from pathlib import Path

# Python 3.13 removed audioop from stdlib; discord.py voice still imports it.
try:
    import audioop  # type: ignore
except ModuleNotFoundError:
    try:
        import audioop_lts as audioop  # type: ignore
        sys.modules['audioop'] = audioop
    except ModuleNotFoundError:
        pass

import discord
from discord.ext import commands

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / 'config.json'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Load config
with CONFIG_PATH.open('r', encoding='utf-8') as f:
    config = json.load(f)


def reload_config():
    """Reload runtime configuration from disk."""
    global config
    with CONFIG_PATH.open('r', encoding='utf-8') as f:
        config = json.load(f)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

if sys.version_info >= (3, 13):
    logger.warning('Python 3.13 detected. Discord voice/music is not reliable in this setup; use Python 3.11 or 3.12 on PebbleHost.')

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix=config['bot'].get('prefix', '!'),
    intents=intents,
    help_command=None
)

# Get bot token from environment first (best for hosted platforms like PebbleHost)
TOKEN = (os.getenv('DISCORD_TOKEN') or config.get('token') or '').strip()


async def update_roster_message(guild: discord.Guild, reason: str):
    """Refresh the configured persistent roster message, if one exists."""
    reload_config()

    roster_config = config.get('roster', {})
    display_channel_id = roster_config.get('display_channel')
    roster_message_id = roster_config.get('roster_message_id')

    if not display_channel_id or not roster_message_id:
        return

    try:
        channel = bot.get_channel(display_channel_id)
        if not channel:
            logger.warning('Roster display channel not found: %s', display_channel_id)
            return

        message = await channel.fetch_message(roster_message_id)
        roster_cog = bot.get_cog('Roster')
        if not roster_cog:
            logger.error('Roster cog not found')
            return

        embed = await roster_cog._create_roster_embed(guild)
        await message.edit(embed=embed)
        logger.info('Auto-updated roster message due to %s', reason)
    except discord.NotFound:
        logger.warning('Roster message or channel was deleted')
        config['roster']['display_channel'] = None
        config['roster']['roster_message_id'] = None
        with CONFIG_PATH.open('w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error('Error updating roster message: %s', e)

async def load_cogs():
    """Load all cogs from the cogs directory."""
    cogs_dir = BASE_DIR / 'cogs'
    if not cogs_dir.exists():
        logger.warning('Cogs directory not found: %s', cogs_dir)
        return

    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py') and not filename.startswith('_'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                logger.info('Loaded cog: %s', filename[:-3])
            except Exception as e:
                logger.error('Failed to load cog %s: %s', filename, e)

@bot.event
async def on_ready():
    """Called when the bot is ready."""
    bot.start_time = discord.utils.utcnow()
    logger.info('Logged in as %s (ID: %s)', bot.user, bot.user.id)
    logger.info('------')

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f'Synced {len(synced)} slash commands')
    except Exception as e:
        logger.error(f'Failed to sync slash commands: {e}')

    activity_type = config['bot'].get('activity_type', '').lower()
    activity_text = config['bot'].get('activity_text', '')
    status_name = config['bot'].get('status', 'online').lower()

    if activity_type == 'playing':
        activity = discord.Activity(type=discord.ActivityType.playing, name=activity_text)
    elif activity_type == 'watching':
        activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
    elif activity_type == 'listening':
        activity = discord.Activity(type=discord.ActivityType.listening, name=activity_text)
    else:
        activity = None

    status = getattr(discord.Status, status_name, discord.Status.online)
    await bot.change_presence(activity=activity, status=status)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        logger.warning('Command not found: %s', ctx.message.content)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f'Missing required argument: {error.param.name}')
    else:
        logger.error('Command error: %s', error)
        await ctx.send('An error occurred while processing the command.')

@bot.event
async def on_member_update(before, after):
    """Handle member role updates to auto-update roster and announce promotions."""
    reload_config()

    roles_changed = before.roles != after.roles
    nickname_changed = before.display_name != after.display_name

    if not roles_changed and not nickname_changed:
        return
    
    # Get roster configuration
    roster_config = config.get('roster', {})
    promotion_channel_id = roster_config.get('promotion_channel')
    roster_roles = set(roster_config.get('roles', []))
    
    await update_roster_message(after.guild, f'member update for {after.display_name}')
    
    # Handle promotion announcements
    if roles_changed and promotion_channel_id and roster_roles:
        logger.info('Checking for promotions: channel=%s, roster_roles=%s', promotion_channel_id, len(roster_roles))
        try:
            # Find newly added roles that are in the roster
            before_role_ids = {role.id for role in before.roles}
            after_role_ids = {role.id for role in after.roles}
            added_role_ids = after_role_ids - before_role_ids
            promoted_roles = added_role_ids & roster_roles
            
            logger.info('Role change detected: before=%s, after=%s, added=%s, promoted=%s', 
                       len(before_role_ids), len(after_role_ids), len(added_role_ids), len(promoted_roles))
            
            if promoted_roles:
                logger.info('Promoted roles found: %s', promoted_roles)
                # Get the promotion channel
                promo_channel = bot.get_channel(promotion_channel_id)
                if not promo_channel:
                    logger.error('Promotion channel not found: %s', promotion_channel_id)
                    return
                
                logger.info('Promotion channel found: %s (%s)', promo_channel.name, promo_channel.id)
                
                # Check if bot can send messages
                if not promo_channel.permissions_for(promo_channel.guild.me).send_messages:
                    logger.error('Bot does not have permission to send messages in promotion channel')
                    return
                
                # Get role names
                role_names = []
                for role_id in promoted_roles:
                    role = after.guild.get_role(role_id)
                    if role:
                        role_names.append(role.name)
                        logger.info('Found role: %s (%s)', role.name, role.id)
                    else:
                        logger.warning('Role not found: %s', role_id)
                
                if role_names:
                    # Create promotion message
                    role_text = ", ".join(f"**{name}**" for name in role_names)
                    embed = discord.Embed(
                        title="🎉 Promotion Announcement!",
                        description=f"Congratulations {after.mention}! You have been promoted to {role_text}!",
                        color=discord.Color.gold(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="Royal Family Promotions")
                    
                    # Send the promotion message
                    await promo_channel.send(embed=embed)
                    logger.info('Posted promotion announcement for %s: %s', after.display_name, role_text)
                else:
                    logger.warning('No role names found for promoted roles: %s', promoted_roles)
            else:
                logger.debug('No roster roles were added to %s', after.display_name)
                    
        except Exception as e:
            logger.error('Error posting promotion announcement: %s', e)
            import traceback
            logger.error('Traceback: %s', traceback.format_exc())


@bot.event
async def on_member_remove(member):
    """Refresh roster when a member leaves the guild."""
    await update_roster_message(member.guild, f'member leave for {member.display_name}')

async def main():
    """Main bot startup function."""
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

if __name__ == '__main__':
    if not TOKEN or TOKEN == 'your_bot_token_here':
        logger.error('Discord token not set. Configure DISCORD_TOKEN in environment variables for PebbleHost.')
        exit(1)

    import asyncio
    asyncio.run(main())
