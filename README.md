# Discord Bot

A modular Discord bot with configurable settings and separate cog-based modules.

## Project Structure

```
DISCORD BOT/
├── main.py              # Main bot file
├── config.json          # Bot configuration
├── .env                 # Environment variables (keep secret!)
├── requirements.txt     # Python dependencies
├── README.md            # This file
├── cogs/                # Bot command modules (cogs)
│   ├── __init__.py
│   ├── utility.py       # Utility commands (ping, info, echo)
│   └── moderation.py    # Moderation commands (kick, ban, clear)
├── modules/             # Helper modules (optional)
└── logs/                # Log files
```

## Setup Instructions

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure the Bot

1. **Create a Discord Application:**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application"
   - Go to "Bot" section and click "Add Bot"
   - Copy the bot token

2. **Configure `config.json`:**
   - Set `token` to your Discord bot token
   - Set `owner_id` to your Discord user ID
   - Adjust the `bot` settings (prefix, activity, status)
   - Enable/disable specific features

### 3. Run the Bot

```bash
python main.py
```

## PebbleHost Deployment

Use these settings in PebbleHost to run the bot reliably:

- Startup command: `python main.py`
- Python version: 3.10+ recommended
- Install command: `pip install -r requirements.txt`
- Environment variable: `DISCORD_TOKEN=your_real_bot_token`
- Optional for YouTube on restricted IPs: `YTDLP_COOKIES_FILE=/home/container/cookies.txt`

Notes:

- The bot now prefers `DISCORD_TOKEN` from environment variables.
- Keep `config.json` token empty or placeholder in production.
- Make sure Privileged Gateway Intents are enabled in Discord Developer Portal (Message Content and Server Members), since this bot uses both.
- Music commands require FFmpeg. If PebbleHost does not expose ffmpeg in PATH, set `FFMPEG_PATH` to your ffmpeg binary path.
- If YouTube returns "Sign in to confirm you're not a bot", upload a `cookies.txt` file and set `YTDLP_COOKIES_FILE`.
- Use Python 3.10 to 3.12 when possible.
- Python 3.13 removes `audioop`; this project includes a fallback via `audioop-lts` for voice support.
- If voice repeatedly fails with Discord close code `4006`, switch the server runtime to Python 3.11/3.12 and restart. On some low-cost hosts this can also indicate temporary voice networking limits.

## Available Commands

### Utility Cog
- `!ping` - Check bot latency
- `!info` - Get bot information
- `!echo <message>` - Echo a message

### Moderation Cog
- `!kick <member> [reason]` - Kick a member
- `!ban <member> [reason]` - Ban a member
- `!clear [amount]` - Clear messages (default: 10)

### Music Cog (Slash Commands)
- `/play <query>` - Play a YouTube URL or search term
- `/skip` - Skip current track
- `/stop` - Stop playback, clear queue, disconnect bot

### Roster Cog
- `!roster` - Display the organization roster with members organized by role
- `!roster add @role` - Add a role to the roster (Admin only)
- `!roster remove @role` - Remove a role from the roster (Admin only)
- `!roster list` - List all roles currently in the roster
- `!roster reorder role1, role2, role3` - Reorder roster roles (Admin only)

## Creating New Cogs

1. Create a new Python file in the `cogs/` directory
2. Follow the template:

```python
import discord
from discord.ext import commands

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='mycommand')
    async def my_command(self, ctx):
        """My command description"""
        await ctx.send("Hello!")

async def setup(bot):
    await bot.add_cog(MyCog(bot))
```

3. Save the file - it will be automatically loaded by `main.py`

## Roster Setup Guide

The roster feature displays your organization's hierarchy with members organized by role.

### Step 1: Create Discord Roles

Create roles in your Discord server for each position/rank (e.g., Owner/Leader, Underboss, Captain, etc.).

### Step 2: Add Roles to Roster

Run commands to add roles to the roster:
```
!roster add @Owner/Leader
!roster add @Underboss
!roster add @Captain
!roster add @Lieutenant
```

### Step 3: Verify Roster Roles

Run `!roster list` to see all configured roles:
```
📋 Roster Roles
1. Owner/Leader
2. Underboss
3. Captain
4. Lieutenant
```

### Step 4: Display Roster

Run `!roster` to display the complete organization roster with all members:

```
🎖️ Organization Roster

〤 Owner/Leader 〤
    〤 @Dx | Dx
    〤 @Nick | Nick

〤 Underboss 〤

〤 Captain 〤
    〤 @Adrian Prince | Adrian Prince
    〤 @Peasy | Peasy

〤 Lieutenant 〤
    〤 @Syd | Syd
    〤 @Ronnie Jones | Ronnie Jones

———————————————————
Total Members: 10/150
———————————————————
```

### Managing Roster

**Remove a role:**
```
!roster remove @Underboss
```

**Reorder roles (change priority):**
```
!roster reorder Owner/Leader, Captain, Underboss, Lieutenant
```

All changes are saved to `config.json` automatically.

## Configuration Options

Edit `config.json` to customize:

- **prefix**: Command prefix (default: `!`)
- **activity_type**: `playing`, `watching`, or `listening`
- **activity_text**: Status text
- **features**: Enable/disable specific features
- **colors**: Embed color codes

## Logging

Logs are saved to `logs/bot.log` and also printed to the console.

## Troubleshooting

- **Bot won't start:** Check that `token` is set in `config.json` and is not the default placeholder
- **Commands not working:** Verify the bot has necessary permissions in the channel
- **Cogs not loading:** Check the logs for error messages
