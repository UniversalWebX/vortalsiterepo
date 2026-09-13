"""Server partnerships: /partner setup, toggle, browse, request, list, remove.

Partnering is off by default and has to be turned on per server by someone
with Manage Server. A partnership only forms when *both* sides accept, and
adverts are only ever posted into the channel each server nominated itself —
so the bot can never be used to blast promos into servers that didn't ask.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.partner")

MAX_DESCRIPTION = 400


def guild_ad(bot: commands.Bot, guild_id: int, config: dict) -> discord.Embed:
    guild = bot.get_guild(guild_id)
    name = guild.name if guild else f"Server {guild_id}"
    embed = base_embed(f"🤝 {name}")
    embed.description = config.get("description") or "*No description set.*"
    if guild:
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
    if config.get("invite_url"):
        embed.add_field(name="Invite", value=config["invite_url"], inline=True)
    embed.set_footer(text=f"Server ID: {guild_id} • DonutDuck partners")
    return embed


class PartnerRequestView(discord.ui.View):
    """Posted into the *target* server's partner channel. Only their staff can act."""

    def __init__(self, bot: commands.Bot, requester_id: int, target_id: int):
        super().__init__(timeout=None)  # persists until answered
        self.bot = bot
        self.requester_id = requester_id
        self.target_id = target_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Only someone with **Manage Server** can answer partner requests.",
                ephemeral=True,
            )
            return False
        return True

    def _disable(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="🤝")
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        db = self.bot.db

        pending = await db.pending_between(self.requester_id, self.target_id)
        if not pending:
            self._disable()
            await interaction.edit_original_response(view=self)
            await interaction.followup.send(
                "That request is no longer pending.", ephemeral=True
            )
            return

        await db.set_partnership_status(self.requester_id, self.target_id, "accepted")
        self._disable()
        await interaction.edit_original_response(view=self)

        requester_cfg = await db.get_config(self.requester_id)
        target_cfg = await db.get_config(self.target_id)

        # Each server gets the *other* server's advert in its own channel.
        await self._post(self.target_id, target_cfg, guild_ad(self.bot, self.requester_id, requester_cfg))
        await self._post(self.requester_id, requester_cfg, guild_ad(self.bot, self.target_id, target_cfg))

        requester = self.bot.get_guild(self.requester_id)
        await interaction.followup.send(
            embed=base_embed(
                "🤝 Partnership accepted",
                f"You're now partnered with **{requester.name if requester else self.requester_id}**.",
            )
        )
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer()
        await self.bot.db.set_partnership_status(
            self.requester_id, self.target_id, "declined"
        )
        self._disable()
        await interaction.edit_original_response(view=self)
        await interaction.followup.send("Request declined.", ephemeral=True)
        self.stop()

    async def _post(self, guild_id: int, config: dict, embed: discord.Embed) -> None:
        channel = self.bot.get_channel(config.get("partner_channel") or 0)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.warning("Couldn't post partner ad to guild %s", guild_id)


class Partner(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(
        name="partner",
        description="Partner with other DonutSMP servers",
        guild_only=True,
    )

    # ---------------------------------------------------------- autocomplete

    async def partner_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        rows = await self.bot.db.partner_enabled_guilds()
        choices = []
        for row in rows:
            gid = row["guild_id"]
            if gid == interaction.guild_id:
                continue
            guild = self.bot.get_guild(gid)
            name = guild.name if guild else str(gid)
            if current.lower() in name.lower() or current in str(gid):
                choices.append(app_commands.Choice(name=name[:100], value=str(gid)))
        return choices[:25]

    # ---------------------------------------------------------------- setup

    @group.command(name="setup", description="Configure this server's partner listing")
    @app_commands.describe(
        channel="Where partner adverts and requests get posted",
        invite="A permanent invite link to this server",
        description="A short pitch shown to other servers",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        invite: str,
        description: str,
    ):
        if not invite.startswith(("https://discord.gg/", "https://discord.com/invite/")):
            await interaction.response.send_message(
                embed=error_embed("That doesn't look like a Discord invite link."),
                ephemeral=True,
            )
            return

        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.response.send_message(
                embed=error_embed(
                    f"I need Send Messages and Embed Links in {channel.mention}."
                ),
                ephemeral=True,
            )
            return

        await self.bot.db.set_config(
            interaction.guild_id,
            partner_channel=channel.id,
            invite_url=invite,
            description=description[:MAX_DESCRIPTION],
            partners_enabled=1,
        )

        config = await self.bot.db.get_config(interaction.guild_id)
        embed = base_embed(
            "✅ Partner listing saved",
            "Partnering is now **enabled**. Other servers can find you with "
            "`/partner browse`. Turn it off any time with `/partner toggle`.",
        )
        await interaction.response.send_message(embed=embed)
        await interaction.followup.send(
            content="This is how other servers will see you:",
            embed=guild_ad(self.bot, interaction.guild_id, config),
        )

    @group.command(name="toggle", description="Enable or disable partnering here")
    @app_commands.describe(enabled="Whether this server accepts partner requests")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle(self, interaction: discord.Interaction, enabled: bool):
        config = await self.bot.db.get_config(interaction.guild_id)
        if enabled and not config.get("partner_channel"):
            await interaction.response.send_message(
                embed=error_embed("Run `/partner setup` first."), ephemeral=True
            )
            return

        await self.bot.db.set_config(
            interaction.guild_id, partners_enabled=1 if enabled else 0
        )
        state = "enabled" if enabled else "disabled"
        await interaction.response.send_message(
            embed=base_embed(
                f"🤝 Partnering {state}",
                "You'll no longer appear in `/partner browse` or receive requests."
                if not enabled
                else "You're listed and can send and receive requests.",
            )
        )

    @group.command(name="config", description="Show this server's partner settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config_cmd(self, interaction: discord.Interaction):
        config = await self.bot.db.get_config(interaction.guild_id)
        embed = base_embed("⚙️ Partner config")
        embed.add_field(
            name="Partnering",
            value="🟢 Enabled" if config["partners_enabled"] else "⚫ Disabled",
            inline=True,
        )
        embed.add_field(
            name="Channel",
            value=f"<#{config['partner_channel']}>" if config["partner_channel"] else "not set",
            inline=True,
        )
        embed.add_field(name="Invite", value=config["invite_url"] or "not set", inline=False)
        embed.add_field(
            name="Description", value=config["description"] or "not set", inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --------------------------------------------------------------- browse

    @group.command(name="browse", description="See servers open to partnering")
    async def browse(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.partner_enabled_guilds()
        others = [r for r in rows if r["guild_id"] != interaction.guild_id]

        if not others:
            await interaction.followup.send(
                embed=base_embed(
                    "🤝 No servers listed yet",
                    "Nobody else has partnering enabled right now.",
                )
            )
            return

        embed = base_embed(f"🤝 {len(others)} server(s) open to partnering")
        lines = []
        for row in others[:15]:
            guild = self.bot.get_guild(row["guild_id"])
            name = guild.name if guild else f"Server {row['guild_id']}"
            members = f" · {guild.member_count:,} members" if guild else ""
            desc = (row["description"] or "")[:80]
            lines.append(f"**{name}**{members}\n{desc}\n`/partner request {row['guild_id']}`")
        embed.description = "\n\n".join(lines)
        await interaction.followup.send(embed=embed)

    # -------------------------------------------------------------- request

    @group.command(name="request", description="Ask another server to partner")
    @app_commands.describe(server="The server to send a request to")
    @app_commands.autocomplete(server=partner_autocomplete)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def request(self, interaction: discord.Interaction, server: str):
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db

        try:
            target_id = int(server)
        except ValueError:
            await interaction.followup.send(
                embed=error_embed("That isn't a valid server ID.")
            )
            return

        if target_id == interaction.guild_id:
            await interaction.followup.send(
                embed=error_embed("You can't partner with yourself.")
            )
            return

        own = await db.get_config(interaction.guild_id)
        if not own["partners_enabled"] or not own["partner_channel"]:
            await interaction.followup.send(
                embed=error_embed("Run `/partner setup` here first.")
            )
            return

        target = await db.get_config(target_id)
        target_guild = self.bot.get_guild(target_id)
        if not target_guild or not target["partners_enabled"] or not target["partner_channel"]:
            await interaction.followup.send(
                embed=error_embed("That server isn't accepting partner requests.")
            )
            return

        result = await db.create_request(
            interaction.guild_id, target_id, interaction.user.id
        )
        if result == "already_partners":
            await interaction.followup.send(
                embed=error_embed(f"You're already partnered with **{target_guild.name}**.")
            )
            return
        if result == "already_pending":
            await interaction.followup.send(
                embed=error_embed("There's already a pending request with that server.")
            )
            return

        channel = self.bot.get_channel(target["partner_channel"])
        if channel is None:
            await db.remove_partnership(interaction.guild_id, target_id)
            await interaction.followup.send(
                embed=error_embed("I can't reach that server's partner channel.")
            )
            return

        own_ad = guild_ad(self.bot, interaction.guild_id, own)
        own_ad.title = f"🤝 Partner request from {interaction.guild.name}"
        view = PartnerRequestView(self.bot, interaction.guild_id, target_id)

        try:
            await channel.send(embed=own_ad, view=view)
        except discord.HTTPException:
            await db.remove_partnership(interaction.guild_id, target_id)
            await interaction.followup.send(
                embed=error_embed("Couldn't deliver the request to that server.")
            )
            return

        await interaction.followup.send(
            embed=base_embed(
                "📨 Request sent",
                f"**{target_guild.name}** has been asked. Their staff will accept or decline.",
            )
        )

    # ----------------------------------------------------------- list/remove

    @group.command(name="list", description="Show this server's partners")
    async def list_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        accepted = await self.bot.db.partnerships_for(interaction.guild_id, "accepted")
        pending = await self.bot.db.partnerships_for(interaction.guild_id, "pending")

        embed = base_embed("🤝 Partnerships")
        if accepted:
            lines = []
            for entry in accepted:
                guild = self.bot.get_guild(entry["other_guild"])
                name = guild.name if guild else f"Server {entry['other_guild']}"
                lines.append(f"• **{name}** — since <t:{int(entry['created_at'])}:D>")
            embed.add_field(name=f"Active ({len(accepted)})", value="\n".join(lines[:15]), inline=False)
        else:
            embed.add_field(
                name="Active", value="None yet — try `/partner browse`.", inline=False
            )

        if pending:
            lines = []
            for entry in pending:
                guild = self.bot.get_guild(entry["other_guild"])
                name = guild.name if guild else f"Server {entry['other_guild']}"
                lines.append(f"• {name}")
            embed.add_field(name=f"Pending ({len(pending)})", value="\n".join(lines[:10]), inline=False)

        await interaction.followup.send(embed=embed)

    @group.command(name="remove", description="End a partnership")
    @app_commands.describe(server="Server ID of the partner to remove")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, server: str):
        try:
            target_id = int(server)
        except ValueError:
            await interaction.response.send_message(
                embed=error_embed("That isn't a valid server ID."), ephemeral=True
            )
            return

        removed = await self.bot.db.remove_partnership(interaction.guild_id, target_id)
        guild = self.bot.get_guild(target_id)
        name = guild.name if guild else str(target_id)
        if removed:
            await interaction.response.send_message(
                embed=base_embed("🤝 Partnership ended", f"No longer partnered with **{name}**.")
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(f"No partnership found with **{name}**."), ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Partner(bot))
