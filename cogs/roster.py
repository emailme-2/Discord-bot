import discord
from discord import app_commands
from discord.ext import commands
import logging
from pathlib import Path

from modules.config import load_config, save_config

logger = logging.getLogger(__name__)

class Roster(commands.Cog):
    """Roster management commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.config_file = Path(__file__).resolve().parent.parent / 'config.json'
        self.load_config()
    
    def load_config(self):
        """Load configuration from file"""
        self.config = load_config(self.config_file)

    def save_config(self):
        """Save configuration to file"""
        save_config(self.config_file, self.config)

    def _parse_member_id(self, member_input: str):
        member_input = member_input.strip()
        if member_input.isdigit():
            return int(member_input)
        if member_input.startswith('<@') and member_input.endswith('>'):
            inner = member_input[2:-1]
            if inner.startswith('!') or inner.startswith('&'):
                inner = inner[1:]
            if inner.isdigit():
                return int(inner)
        return None

    def _get_priority_role_id(self):
        return 1315554669220859946

    def _get_roster_members(self, guild, exclude_priority_role=False):
        self.load_config()

        roles_order = self._get_ordered_roles(self.config['roster']['roles'])
        excluded_member_ids = set(self.config['roster'].get('exclude_members', []))
        included_member_ids = set(self.config['roster'].get('include_members', []))
        shown_member_ids = set()
        roster_members = []
        priority_role_id = self._get_priority_role_id()

        for role_id in roles_order:
            if exclude_priority_role and role_id == priority_role_id:
                continue

            role = guild.get_role(role_id)
            if not role:
                continue

            for member in role.members:
                if member.bot:
                    continue
                if member.id in excluded_member_ids or member.id in shown_member_ids:
                    continue
                if exclude_priority_role and self._has_priority_role(member):
                    continue
                if role_id != priority_role_id and self._has_priority_role(member):
                    continue

                roster_members.append(member)
                shown_member_ids.add(member.id)

        for member_id in included_member_ids:
            if member_id in excluded_member_ids or member_id in shown_member_ids:
                continue

            member = guild.get_member(member_id)
            if not member or member.bot:
                continue
            if exclude_priority_role and self._has_priority_role(member):
                continue
            if not exclude_priority_role and self._has_priority_role(member):
                continue

            roster_members.append(member)
            shown_member_ids.add(member.id)

        return roster_members

    async def _find_message_by_id(self, guild, message_id):
        searchable_channels = list(guild.text_channels) + list(guild.threads)

        for target_channel in searchable_channels:
            permissions = target_channel.permissions_for(guild.me)
            if not permissions.read_message_history:
                continue

            try:
                message = await target_channel.fetch_message(message_id)
                return message
            except (discord.NotFound, discord.Forbidden):
                continue
            except Exception:
                continue

        return None

# ── Command Groups ────────────────────────────────────────────────────────
    roster  = app_commands.Group(name="roster",  description="Roster management commands")
    role    = app_commands.Group(name="role",    description="Manage roster roles",   parent=roster)
    member  = app_commands.Group(name="member",  description="Manage roster members", parent=roster)
    setup   = app_commands.Group(name="setup",   description="Configure roster settings", parent=roster)

    # ── /roster show ──────────────────────────────────────────────────────────
    @roster.command(name="show", description="Display the server roster")
    async def roster_show(self, interaction: discord.Interaction):
        await self.display_roster_slash(interaction)

    # ── /roster reactions ─────────────────────────────────────────────────────
    @roster.command(name="reactions", description="Show roster members who have not reacted to a message")
    @app_commands.describe(message_id="The message ID to check reactions on")
    @app_commands.checks.has_permissions(administrator=True)
    async def roster_reactions(self, interaction: discord.Interaction, message_id: str):
        if not message_id.strip().isdigit():
            await interaction.response.send_message("Please provide a valid message ID.", ephemeral=True)
            return

        await interaction.response.defer()

        message = await self._find_message_by_id(interaction.guild, int(message_id.strip()))
        if not message:
            await interaction.followup.send("I couldn't find that message in any channel I can read.")
            return

        reacted_user_ids = set()
        for reaction in message.reactions:
            async for user in reaction.users():
                reacted_user_ids.add(user.id)

        roster_members = self._get_roster_members(interaction.guild, exclude_priority_role=True)
        missing_members = [m for m in roster_members if m.id not in reacted_user_ids]

        summary_embed = discord.Embed(
            title="📣 Roster Reaction Check",
            description=(
                f"Checking reactions for [this message]({message.jump_url}).\n"
                f"Only roster members are checked, and the reserve role is excluded."
            ),
            color=discord.Color.orange()
        )
        summary_embed.add_field(name="💬 Channel", value=message.channel.mention, inline=True)
        summary_embed.add_field(name="👥 Eligible Members", value=str(len(roster_members)), inline=True)
        summary_embed.add_field(name="⚠️ Missing Reactions", value=str(len(missing_members)), inline=True)

        if not missing_members:
            summary_embed.add_field(name="✅ Status", value="Everyone in the roster reacted to the message.", inline=False)
            await interaction.followup.send(embed=summary_embed)
            return

        mention_chunks = [missing_members[i:i + 20] for i in range(0, len(missing_members), 20)]
        await interaction.followup.send(content=' '.join(m.mention for m in mention_chunks[0]), embed=summary_embed)
        for chunk in mention_chunks[1:]:
            await interaction.followup.send(content=' '.join(m.mention for m in chunk))

    # ── /roster test ──────────────────────────────────────────────────────────
    @roster.command(name="test", description="Test if promotion announcements are working")
    @app_commands.checks.has_permissions(administrator=True)
    async def roster_test(self, interaction: discord.Interaction):
        promotion_channel_id = self.config['roster'].get('promotion_channel')
        if not promotion_channel_id:
            await interaction.response.send_message(
                "Promotion channel not configured. Use `/roster setup promotion` first.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        promo_channel = interaction.guild.get_channel(promotion_channel_id)
        if not promo_channel:
            await interaction.followup.send(f"Promotion channel with ID {promotion_channel_id} not found.", ephemeral=True)
            return

        if not promo_channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.followup.send(f"I don't have permission to send messages in {promo_channel.mention}.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🧪 Test Promotion Announcement",
            description="This is a test message to verify promotion announcements are working!",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Royal Family Test")
        await promo_channel.send(embed=embed)
        await interaction.followup.send(f"✅ Test message sent to {promo_channel.mention}!", ephemeral=True)

    # ── /roster role add ──────────────────────────────────────────────────────
    @role.command(name="add", description="Add a role to the roster")
    @app_commands.describe(role="The role to add to the roster")
    @app_commands.checks.has_permissions(administrator=True)
    async def role_add(self, interaction: discord.Interaction, role: discord.Role):
        current_roles = self.config['roster']['roles']
        if role.id in current_roles:
            await interaction.response.send_message(embed=discord.Embed(
                title="⚠️ Role Already Added",
                description=f"{role.mention} is already in the roster.",
                color=discord.Color.orange()
            ))
            return

        current_roles.append(role.id)
        self.save_config()

        embed = discord.Embed(
            title="✅ Role Added",
            description=f"{role.mention} has been added to the roster.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Current Roster Order",
            value='\n'.join([f"{i+1}. {interaction.guild.get_role(r).name if interaction.guild.get_role(r) else 'Unknown Role'}" for i, r in enumerate(current_roles)]),
            inline=False
        )
        await interaction.response.send_message(embed=embed)
        logger.info(f"Role {role.name} ({role.id}) added to roster by {interaction.user} in {interaction.guild}")

    # ── /roster role remove ───────────────────────────────────────────────────
    @role.command(name="remove", description="Remove a role from the roster")
    @app_commands.describe(role="The role to remove from the roster")
    @app_commands.checks.has_permissions(administrator=True)
    async def role_remove(self, interaction: discord.Interaction, role: discord.Role):
        current_roles = self.config['roster']['roles']
        if role.id not in current_roles:
            await interaction.response.send_message(embed=discord.Embed(
                title="⚠️ Role Not Found",
                description=f"{role.mention} is not in the roster.",
                color=discord.Color.orange()
            ))
            return

        current_roles.remove(role.id)
        self.save_config()

        embed = discord.Embed(
            title="✅ Role Removed",
            description=f"{role.mention} has been removed from the roster.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Current Roster Order",
            value='\n'.join([f"{i+1}. {interaction.guild.get_role(r).name if interaction.guild.get_role(r) else 'Unknown Role'}" for i, r in enumerate(current_roles)]) or "No roles in roster",
            inline=False
        )
        await interaction.response.send_message(embed=embed)
        logger.info(f"Role {role.name} ({role.id}) removed from roster by {interaction.user} in {interaction.guild}")

    # ── /roster role list ─────────────────────────────────────────────────────
    @role.command(name="list", description="List all roles in the roster")
    async def role_list(self, interaction: discord.Interaction):
        current_roles = self.config['roster']['roles']
        if not current_roles:
            await interaction.response.send_message(embed=discord.Embed(
                title="📋 Roster Roles",
                description="No roles configured yet. Use `/roster role add` to add roles.",
                color=discord.Color.blue()
            ))
            return

        role_lines = []
        for i, role_id in enumerate(current_roles):
            r = interaction.guild.get_role(role_id)
            role_lines.append(f"{i+1}. {r.name if r else f'Unknown Role'} (`{role_id}`)")

        embed = discord.Embed(title="📋 Roster Roles", description='\n'.join(role_lines), color=discord.Color.blue())
        embed.add_field(name="Total Roles", value=len(current_roles), inline=True)
        include_count = len(self.config['roster'].get('include_members', []))
        exclude_count = len(self.config['roster'].get('exclude_members', []))
        if include_count:
            embed.add_field(name="Included Members", value=str(include_count), inline=True)
        if exclude_count:
            embed.add_field(name="Excluded Members", value=str(exclude_count), inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /roster role reorder ──────────────────────────────────────────────────
    @role.command(name="reorder", description="Reorder roster roles")
    @app_commands.describe(roles="Comma-separated role IDs or mentions in the desired order")
    @app_commands.checks.has_permissions(administrator=True)
    async def role_reorder(self, interaction: discord.Interaction, roles: str):
        roles_input = [r.strip() for r in roles.split(',')]
        valid_roles, invalid_roles = [], []

        for role_input in roles_input:
            if not role_input:
                continue
            r = None
            if role_input.isdigit():
                r = interaction.guild.get_role(int(role_input))
            elif role_input.startswith('<@&') and role_input.endswith('>'):
                rid = role_input[3:-1]
                if rid.isdigit():
                    r = interaction.guild.get_role(int(rid))
            if not r:
                r = discord.utils.find(lambda x: x.name.lower() == role_input.lower(), interaction.guild.roles)
            if r:
                valid_roles.append(r.id)
            else:
                invalid_roles.append(role_input)

        if invalid_roles:
            await interaction.response.send_message(embed=discord.Embed(
                title="⚠️ Invalid Roles",
                description="The following roles don't exist:\n" + '\n'.join(f"• {r}" for r in invalid_roles),
                color=discord.Color.red()
            ))
            return

        self.config['roster']['roles'] = valid_roles
        self.save_config()

        roles_display = '\n'.join([
            f"{i+1}. {interaction.guild.get_role(rid).name if interaction.guild.get_role(rid) else 'Unknown Role'} (`{rid}`)"
            for i, rid in enumerate(valid_roles)
        ])
        embed = discord.Embed(title="✅ Roster Reordered", description="Roster hierarchy reordered successfully!", color=discord.Color.green())
        embed.add_field(name="New Order", value=roles_display, inline=False)
        await interaction.response.send_message(embed=embed)
        logger.info(f"Roster reordered by {interaction.user} in {interaction.guild}")

    # ── /roster member include ────────────────────────────────────────────────
    @member.command(name="include", description="Manually include a member in the roster")
    @app_commands.describe(member="The member to include (mention or ID)")
    @app_commands.checks.has_permissions(administrator=True)
    async def member_include(self, interaction: discord.Interaction, member: str):
        member_id = self._parse_member_id(member)
        if member_id is None:
            await interaction.response.send_message("Please provide a valid user ID or mention.", ephemeral=True)
            return

        member_obj = interaction.guild.get_member(member_id)
        if member_obj is None:
            await interaction.response.send_message("That member is not in this server.", ephemeral=True)
            return

        include_members = self.config['roster'].get('include_members', [])
        exclude_members = self.config['roster'].get('exclude_members', [])

        if member_id in include_members:
            await interaction.response.send_message(f"{member_obj.mention} is already included in the roster.")
            return
        if member_id in exclude_members:
            exclude_members.remove(member_id)

        include_members.append(member_id)
        self.config['roster']['include_members'] = include_members
        self.config['roster']['exclude_members'] = exclude_members
        self.save_config()
        await interaction.response.send_message(f"✅ {member_obj.mention} has been included in the roster.")

    # ── /roster member exclude ────────────────────────────────────────────────
    @member.command(name="exclude", description="Exclude a member from the roster")
    @app_commands.describe(member="The member to exclude (mention or ID)")
    @app_commands.checks.has_permissions(administrator=True)
    async def member_exclude(self, interaction: discord.Interaction, member: str):
        member_id = self._parse_member_id(member)
        if member_id is None:
            await interaction.response.send_message("Please provide a valid user ID or mention.", ephemeral=True)
            return

        member_obj = interaction.guild.get_member(member_id)
        if member_obj is None:
            await interaction.response.send_message("That member is not in this server.", ephemeral=True)
            return

        exclude_members = self.config['roster'].get('exclude_members', [])
        include_members = self.config['roster'].get('include_members', [])

        if member_id in exclude_members:
            await interaction.response.send_message(f"{member_obj.mention} is already excluded from the roster.")
            return
        if member_id in include_members:
            include_members.remove(member_id)

        exclude_members.append(member_id)
        self.config['roster']['exclude_members'] = exclude_members
        self.config['roster']['include_members'] = include_members
        self.save_config()
        await interaction.response.send_message(f"✅ {member_obj.mention} has been excluded from the roster.")

    # ── /roster setup display ─────────────────────────────────────────────────
    @setup.command(name="display", description="Set up a persistent auto-updating roster message in a channel")
    @app_commands.describe(channel="The channel to display the roster in")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_display(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        embed = await self._create_roster_embed(interaction.guild)
        try:
            message = await channel.send(embed=embed)
            self.config['roster']['display_channel'] = channel.id
            self.config['roster']['roster_message_id'] = message.id
            self.save_config()
            await interaction.followup.send(f"✅ Persistent roster set up in {channel.mention}. It will auto-update when roles change.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to send messages in that channel.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

    # ── /roster setup promotion ───────────────────────────────────────────────
    @setup.command(name="promotion", description="Set a channel for promotion announcements")
    @app_commands.describe(channel="The channel to post promotion announcements in")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_promotion(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        self.config['roster']['promotion_channel'] = channel.id
        self.save_config()
        await interaction.followup.send(f"✅ Promotion announcements will now be posted in {channel.mention}.", ephemeral=True)

    # ── /roster setup name ────────────────────────────────────────────────────
    @setup.command(name="name", description="Set the roster display name")
    @app_commands.describe(name="The new display name for the roster")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_name(self, interaction: discord.Interaction, name: str):
        self.config['roster']['name'] = name.strip()
        self.save_config()
        await interaction.response.send_message(embed=discord.Embed(
            title="✅ Roster Name Updated",
            description=f"Roster display name set to **{self.config['roster']['name']}**.",
            color=discord.Color.green()
        ))

    async def _create_roster_embed(self, guild):
        """Create a roster embed for auto-updating."""
        roster_title = self.config['roster'].get('name', 'Royal Family Roster')
        roles_order = self._get_ordered_roles(self.config['roster']['roles'])
        excluded_member_ids = set(self.config['roster'].get('exclude_members', []))
        included_member_ids = set(self.config['roster'].get('include_members', []))
        shown_member_ids = set()
        
        # Build roster
        roster_text = ""
        roster_member_count = 0
        priority_role_member_count = 0
        priority_role_id = self._get_priority_role_id()
        
        for role_id in roles_order:
            role = guild.get_role(role_id)
            if not role:
                continue  # Skip unknown roles
            
            role_name = role.name
            members_with_role = [m for m in role.members
                                 if not m.bot
                                 and m.id not in excluded_member_ids
                                 and m.id not in shown_member_ids
                                 and (role_id == priority_role_id or not self._has_priority_role(m))]
            
            if not members_with_role:
                continue
            
            roster_text += f"\n**{role_name}**\n"
            
            for member in members_with_role:
                display_name = member.display_name
                roster_text += f"└─ {member.mention} • {display_name}\n"
                shown_member_ids.add(member.id)
                if role_id == priority_role_id:
                    priority_role_member_count += 1
                else:
                    roster_member_count += 1
        
        if included_member_ids:
            extra_members = []
            for member_id in included_member_ids:
                if member_id in excluded_member_ids or member_id in shown_member_ids:
                    continue
                member = guild.get_member(member_id)
                if member and not member.bot and not self._has_priority_role(member):
                    extra_members.append(member)
            if extra_members:
                roster_text += "\n**Included Members**\n"
                for member in extra_members:
                    roster_text += f"└─ {member.mention} • {member.display_name}\n"
                    shown_member_ids.add(member.id)
                    roster_member_count += 1
        
        # Check if roster_text is too long for a single embed (6000 char limit)
        if len(roster_text) > 5800:  # Leave some buffer
            roster_text = roster_text[:5800] + "\n\n*... (truncated due to length)*"
        
        roster_text += "\n" + "═" * 25 + "\n"
        roster_text += f"👥 **Roster Members:** {roster_member_count}\n"
        if priority_role_member_count:
            roster_text += f"⭐ **Priority Role Members:** {priority_role_member_count}\n"
        roster_text += f"📊 **Total Shown Members:** {roster_member_count + priority_role_member_count}\n"
        roster_text += "═" * 25
        
        embed = discord.Embed(
            title=f"🎖️ {roster_title}",
            description=roster_text,
            color=discord.Color.gold()
        )
        embed.set_footer(text="RF ROSTER • Auto-updates when roles change")
        
        return embed

    def _has_priority_role(self, member):
        priority_role_id = self._get_priority_role_id()
        return any(role.id == priority_role_id for role in member.roles)

    def _get_ordered_roles(self, roles_order):
        priority_role_id = self._get_priority_role_id()
        ordered_roles = [role_id for role_id in roles_order if role_id != priority_role_id]
        if priority_role_id in roles_order:
            ordered_roles.append(priority_role_id)
        return ordered_roles

    async def display_roster_slash(self, interaction: discord.Interaction):
        """Display the roster with members organized by role (slash command version)"""
        
        roster_title = self.config['roster'].get('name', 'Royal Family Roster')
        roles_order = self._get_ordered_roles(self.config['roster']['roles'])
        guild = interaction.guild
        excluded_member_ids = set(self.config['roster'].get('exclude_members', []))
        included_member_ids = set(self.config['roster'].get('include_members', []))
        shown_member_ids = set()
        
        if not roles_order and not included_member_ids:
            embed = discord.Embed(
                title="❌ Roster Not Configured",
                description="Use `/roster_add` to add roles to the roster.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        # Build roster
        roster_text = ""
        roster_member_count = 0
        priority_role_member_count = 0
        priority_role_id = self._get_priority_role_id()
        
        for role_id in roles_order:
            role = guild.get_role(role_id)
            if not role:
                continue  # Skip unknown roles
            
            role_name = role.name
            members_with_role = [m for m in role.members
                                 if not m.bot
                                 and m.id not in excluded_member_ids
                                 and m.id not in shown_member_ids
                                 and (role_id == priority_role_id or not self._has_priority_role(m))]
            
            if not members_with_role:
                continue
            
            roster_text += f"\n**{role_name}**\n"
            
            for member in members_with_role:
                display_name = member.display_name
                roster_text += f"└─ {member.mention} • {display_name}\n"
                shown_member_ids.add(member.id)
                if role_id == priority_role_id:
                    priority_role_member_count += 1
                else:
                    roster_member_count += 1
        
        if included_member_ids:
            extra_members = []
            for member_id in included_member_ids:
                if member_id in excluded_member_ids or member_id in shown_member_ids:
                    continue
                member = guild.get_member(member_id)
                if member and not member.bot and not self._has_priority_role(member):
                    extra_members.append(member)
            if extra_members:
                roster_text += "\n**Included Members**\n"
                for member in extra_members:
                    roster_text += f"└─ {member.mention} • {member.display_name}\n"
                    shown_member_ids.add(member.id)
                    roster_member_count += 1
        
        roster_text += "\n" + "═" * 25 + "\n"
        roster_text += f"👥 **Roster Members:** {roster_member_count}\n"
        if priority_role_member_count:
            roster_text += f"⭐ **Priority Role Members:** {priority_role_member_count}\n"
        roster_text += f"📊 **Total Shown Members:** {roster_member_count + priority_role_member_count}\n"
        roster_text += "═" * 25
        
        chunks = [roster_text[i:i+1900] for i in range(0, len(roster_text), 1900)]
        
        for i, chunk in enumerate(chunks):
            if i == 0:
                embed = discord.Embed(
                    title=f"🎖️ {roster_title}",
                    description=chunk,
                    color=discord.Color.gold()
                )
                embed.set_footer(text="RF ROSTER")
                if i == 0:
                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.followup.send(embed=embed)
            else:
                embed = discord.Embed(
                    description=chunk,
                    color=discord.Color.gold()
                )
                await interaction.followup.send(embed=embed)
        
        logger.info(f"Roster displayed in {interaction.guild} by {interaction.user}")

async def setup(bot):
    """Setup function to load the cog"""
    await bot.add_cog(Roster(bot))
