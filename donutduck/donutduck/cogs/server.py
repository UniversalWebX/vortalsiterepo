"""Discord-native server features: welcome/goodbye, autorole, reaction roles
and a starboard.

Reaction roles here are **not** reactions — they're a dropdown (or buttons),
which is better in every way that matters: no Manage Messages needed to clean
up stray reactions, no emoji collisions, a description per option, and a cap
on how many a member may pick. The name is kept because that's what people
search for.

Welcome and goodbye messages support placeholders:
  {user} mention · {name} display name · {tag} full tag
  {server} server name · {count} member count · {id} user id
"""

from __future__ import annotations

import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.server")

RR_SELECT_ID = "dd:rr:select"
MAX_OPTIONS = 25


def render(template: str, member: discord.Member) -> str:
    return (
        (template or "")
        .replace("{user}", member.mention)
        .replace("{name}", member.display_name)
        .replace("{tag}", str(member))
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count or 0))
        .replace("{id}", str(member.id))
    )[:2000]


class ReactionRoleSelect(discord.ui.Select):
    def __init__(self, cog: "Server", key: str, options: list[dict], max_choices: int):
        self.cog = cog
        choices = [
            discord.SelectOption(
                label=option["label"][:100],
                value=str(option["role_id"]),
                description=(option.get("description") or "")[:100] or None,
                emoji=option.get("emoji") or None,
            )
            for option in options[:MAX_OPTIONS]
        ]
        super().__init__(
            custom_id=f"{RR_SELECT_ID}:{key}",
            placeholder="Pick your roles…",
            min_values=0,
            max_values=max_choices if max_choices else len(choices),
            options=choices,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        config = await self.cog.bot.db.reaction_role_by_message(interaction.message.id)
        if config is None:
            await interaction.followup.send(
                embed=error_embed("This role menu is no longer configured."), ephemeral=True
            )
            return

        managed = {int(o["role_id"]) for o in json.loads(config["options"])}
        chosen = {int(v) for v in self.values}

        member = interaction.user
        current = {r.id for r in member.roles}

        to_add = [
            interaction.guild.get_role(r) for r in chosen - current if r in managed
        ]
        # Deselecting removes; only roles this menu manages are ever touched.
        to_remove = [
            interaction.guild.get_role(r)
            for r in (managed & current) - chosen
        ]
        to_add = [r for r in to_add if r]
        to_remove = [r for r in to_remove if r]

        try:
            if to_add:
                await member.add_roles(*to_add, reason="Reaction roles")
            if to_remove:
                await member.remove_roles(*to_remove, reason="Reaction roles")
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(
                    "I can't manage those roles — my own role needs to sit above "
                    "them in the role list, and I need Manage Roles."
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.followup.send(
                embed=error_embed("Discord refused the role change."), ephemeral=True
            )
            return

        parts = []
        if to_add:
            parts.append("Added " + ", ".join(r.mention for r in to_add))
        if to_remove:
            parts.append("Removed " + ", ".join(r.mention for r in to_remove))
        await interaction.followup.send(
            embed=base_embed("🎭 Roles updated", "\n".join(parts) or "No changes.", accent=BLUE),
            ephemeral=True,
        )


class ReactionRoleView(discord.ui.View):
    def __init__(self, cog: "Server", key: str, options: list[dict], max_choices: int = 0):
        super().__init__(timeout=None)
        self.add_item(ReactionRoleSelect(cog, key, options, max_choices))


class Server(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        # Re-register every saved role menu so they survive restarts.
        try:
            for guild in self.bot.guilds:
                for config in await self.bot.db.reaction_roles(guild.id):
                    options = json.loads(config["options"])
                    self.bot.add_view(
                        ReactionRoleView(
                            self, config["key"], options, config["max_choices"]
                        ),
                        message_id=config["message_id"],
                    )
        except Exception:
            log.exception("Couldn't restore reaction role views")

    # ------------------------------------------------- welcome / goodbye

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        settings = await self.bot.db.settings(member.guild.id)

        if settings["autorole"]:
            role = member.guild.get_role(settings["autorole"])
            if role:
                try:
                    await member.add_roles(role, reason="Autorole")
                except discord.HTTPException:
                    log.info("Autorole failed in guild %s", member.guild.id)

        channel = member.guild.get_channel(settings["welcome_channel"] or 0)
        if channel is None:
            return

        embed = base_embed(
            f"👋 Welcome to {member.guild.name}",
            render(settings["welcome_message"] or "{user} just joined!", member),
            accent=BLUE,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        try:
            await channel.send(
                content=member.mention,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        settings = await self.bot.db.settings(member.guild.id)
        channel = member.guild.get_channel(settings["goodbye_channel"] or 0)
        if channel is None:
            return
        try:
            await channel.send(
                embed=base_embed(
                    "👋 Member left",
                    render(settings["goodbye_message"] or "{tag} has left the server.", member),
                    accent=PINK,
                )
            )
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ starboard

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_star(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_star(payload)

    async def _handle_star(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        settings = await self.bot.db.settings(payload.guild_id)
        board_id = settings["starboard_channel"]
        if not board_id or str(payload.emoji) != settings["starboard_emoji"]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        source_channel = guild.get_channel(payload.channel_id) if guild else None
        board = guild.get_channel(board_id) if guild else None
        if source_channel is None or board is None or source_channel.id == board.id:
            return

        try:
            message = await source_channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        reaction = discord.utils.get(
            message.reactions, emoji=settings["starboard_emoji"]
        )
        stars = reaction.count if reaction else 0
        existing = await self.bot.db.get_star_post(message.id)

        if stars < settings["starboard_stars"]:
            # Dropped below the threshold — remove the board post.
            if existing:
                try:
                    old = await board.fetch_message(existing["post_id"])
                    await old.delete()
                except discord.HTTPException:
                    pass
                await self.bot.db.delete_star_post(message.id)
            return

        embed = base_embed(None, message.content or "", accent=YELLOW)
        embed.set_author(
            name=message.author.display_name, icon_url=message.author.display_avatar.url
        )
        embed.add_field(
            name="Source", value=f"[Jump to message]({message.jump_url})", inline=False
        )
        if message.attachments and message.attachments[0].content_type and (
            message.attachments[0].content_type.startswith("image")
        ):
            embed.set_image(url=message.attachments[0].url)
        embed.set_footer(text=f"#{source_channel.name}")

        content = f"{settings['starboard_emoji']} **{stars}**"

        if existing:
            try:
                post = await board.fetch_message(existing["post_id"])
                await post.edit(content=content, embed=embed)
                await self.bot.db.save_star_post(
                    message.id, guild.id, post.id, stars
                )
                return
            except discord.NotFound:
                pass  # deleted by hand; fall through and repost

        try:
            post = await board.send(content=content, embed=embed)
            await self.bot.db.save_star_post(message.id, guild.id, post.id, stars)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ commands

    welcome_group = app_commands.Group(
        name="welcome",
        description="Welcome, goodbye and autorole settings",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @welcome_group.command(name="set", description="Set the welcome message")
    @app_commands.describe(
        channel="Where to post welcomes",
        message="Text. Placeholders: {user} {name} {tag} {server} {count}",
    )
    async def welcome_set(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str | None = None,
    ):
        await self.bot.db.set_settings(
            interaction.guild_id, welcome_channel=channel.id, welcome_message=message
        )
        preview = render(
            message or "{user} just joined!", interaction.user
        )
        embed = base_embed("✅ Welcome set", f"Posting to {channel.mention}.")
        embed.add_field(name="Preview", value=preview, inline=False)
        await interaction.response.send_message(embed=embed)

    @welcome_group.command(name="goodbye", description="Set the goodbye message")
    @app_commands.describe(channel="Where to post them", message="Text with placeholders")
    async def welcome_goodbye(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str | None = None,
    ):
        await self.bot.db.set_settings(
            interaction.guild_id, goodbye_channel=channel.id, goodbye_message=message
        )
        await interaction.response.send_message(
            embed=base_embed("✅ Goodbye set", f"Posting to {channel.mention}.")
        )

    @welcome_group.command(name="autorole", description="Role given to every new member")
    @app_commands.describe(role="Leave blank to disable")
    async def welcome_autorole(
        self, interaction: discord.Interaction, role: discord.Role | None = None
    ):
        if role and role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=error_embed(
                    f"{role.mention} sits above my highest role, so I can't assign it. "
                    "Move my role higher in Server Settings → Roles."
                ),
                ephemeral=True,
            )
            return

        await self.bot.db.set_settings(
            interaction.guild_id, autorole=role.id if role else None
        )
        await interaction.response.send_message(
            embed=base_embed(
                "✅ Autorole updated",
                f"New members get {role.mention}." if role else "Autorole disabled.",
            )
        )

    @welcome_group.command(name="off", description="Turn off welcome and goodbye messages")
    async def welcome_off(self, interaction: discord.Interaction):
        await self.bot.db.set_settings(
            interaction.guild_id, welcome_channel=None, goodbye_channel=None
        )
        await interaction.response.send_message(
            embed=base_embed("✅ Disabled", "Welcome and goodbye messages are off.", accent=PINK)
        )

    # --- reaction roles ---------------------------------------------------

    @app_commands.command(
        name="rolemenu", description="Post a self-assign role menu (dropdown)"
    )
    @app_commands.describe(
        key="Short id for this menu",
        roles="Roles to offer, comma separated mentions or IDs",
        title="Heading for the message",
        description="Text under the heading",
        max_choices="Max roles a member may pick (0 = no limit)",
        channel="Where to post it",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def rolemenu(
        self,
        interaction: discord.Interaction,
        key: str,
        roles: str,
        title: str = "Pick your roles",
        description: str | None = None,
        max_choices: app_commands.Range[int, 0, 25] = 0,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        key = key.lower().strip().replace(" ", "-")[:20]
        target = channel or interaction.channel

        resolved: list[dict] = []
        for token in roles.replace("<@&", " ").replace(">", " ").split(","):
            token = token.strip().strip("<@&>").strip()
            if not token:
                continue
            role = None
            if token.isdigit():
                role = interaction.guild.get_role(int(token))
            if role is None:
                role = discord.utils.get(interaction.guild.roles, name=token)
            if role is None:
                await interaction.followup.send(
                    embed=error_embed(f"Couldn't find a role matching `{token}`.")
                )
                return
            if role >= interaction.guild.me.top_role:
                await interaction.followup.send(
                    embed=error_embed(
                        f"{role.mention} is above my highest role, so I couldn't "
                        "assign it. Move my role above it first."
                    )
                )
                return
            resolved.append({"role_id": role.id, "label": role.name})

        if not resolved:
            await interaction.followup.send(embed=error_embed("No roles given."))
            return
        if len(resolved) > MAX_OPTIONS:
            await interaction.followup.send(
                embed=error_embed(f"A dropdown holds at most {MAX_OPTIONS} options.")
            )
            return

        embed = base_embed(f"🎭 {title}", description or "Choose from the menu below.")
        embed.add_field(
            name="Available",
            value="\n".join(f"<@&{o['role_id']}>" for o in resolved),
            inline=False,
        )
        if max_choices:
            embed.set_footer(text=f"Pick up to {max_choices}")

        view = ReactionRoleView(self, key, resolved, max_choices)
        try:
            message = await target.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(f"I can't post in {target.mention}.")
            )
            return

        saved = await self.bot.db.add_reaction_roles(
            interaction.guild_id,
            key,
            target.id,
            message.id,
            json.dumps(resolved),
            title=title,
            max_choices=max_choices,
        )
        if not saved:
            await message.delete()
            await interaction.followup.send(
                embed=error_embed(f"A menu called `{key}` already exists.")
            )
            return

        self.bot.add_view(
            ReactionRoleView(self, key, resolved, max_choices), message_id=message.id
        )
        await interaction.followup.send(
            embed=base_embed("✅ Role menu posted", f"Live in {target.mention}.")
        )

    @app_commands.command(name="rolemenudelete", description="Remove a role menu")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def rolemenudelete(self, interaction: discord.Interaction, key: str):
        if await self.bot.db.delete_reaction_roles(interaction.guild_id, key):
            await interaction.response.send_message(
                embed=base_embed(
                    "🗑️ Removed",
                    f"`{key}` deleted. The message stays until you delete it.",
                    accent=PINK,
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No menu called `{key}`."), ephemeral=True
            )

    # --- starboard --------------------------------------------------------

    @app_commands.command(name="starboard", description="Configure the starboard")
    @app_commands.describe(
        channel="Where starred messages get reposted (blank to disable)",
        stars="How many reactions are needed",
        emoji="Which emoji counts",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def starboard(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        stars: app_commands.Range[int, 1, 50] = 3,
        emoji: str = "⭐",
    ):
        if channel is None:
            await self.bot.db.set_settings(interaction.guild_id, starboard_channel=None)
            await interaction.response.send_message(
                embed=base_embed("⭐ Starboard disabled", accent=PINK)
            )
            return

        await self.bot.db.set_settings(
            interaction.guild_id,
            starboard_channel=channel.id,
            starboard_stars=stars,
            starboard_emoji=emoji,
        )
        await interaction.response.send_message(
            embed=base_embed(
                "⭐ Starboard enabled",
                f"{emoji} × **{stars}** on any message reposts it to {channel.mention}.",
                accent=YELLOW,
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Server(bot))
