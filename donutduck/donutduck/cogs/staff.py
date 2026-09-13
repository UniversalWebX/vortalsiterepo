"""Staff tooling: role config, activity checks, strikes and legit votes.

`/staffroles` is the important one — it defines who counts as staff, and
tickets, giveaways, activity checks and strikes all read from it.

Activity checks ping every staff role, and anyone who doesn't press the button
before the deadline picks up a strike automatically. Legit votes post a
giveaway to a voting channel where the result is tallied and recorded rather
than counted by hand from reactions.
"""

from __future__ import annotations

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..permissions import is_staff, staff_only, staff_role_objects
from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed

log = logging.getLogger("donutduck.staff")

ACTIVITY_ID = "dd:activity:here"
LEGIT_YES = "dd:legit:yes"
LEGIT_NO = "dd:legit:no"


class ActivityView(discord.ui.View):
    """One button. Pressing it is the whole check."""

    def __init__(self, cog: "Staff", check_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        if check_id is not None:
            self.here.custom_id = f"{ACTIVITY_ID}:{check_id}"

    @staticmethod
    def check_id_from(interaction: discord.Interaction) -> int | None:
        parts = (interaction.data or {}).get("custom_id", "").split(":")
        return int(parts[-1]) if parts and parts[-1].isdigit() else None

    @discord.ui.button(
        label="I'm active", emoji="✅", style=discord.ButtonStyle.success,
        custom_id=ACTIVITY_ID,
    )
    async def here(self, interaction: discord.Interaction, _: discord.ui.Button):
        check_id = self.check_id_from(interaction)
        if check_id is None:
            await interaction.response.send_message(
                embed=error_embed("This check is missing its id."), ephemeral=True
            )
            return

        check = await self.cog.bot.db.get_activity_check(check_id)
        if check is None or check["closed"]:
            await interaction.response.send_message(
                embed=error_embed("This activity check has already closed."),
                ephemeral=True,
            )
            return

        if not await is_staff(self.cog.bot, interaction.user):
            await interaction.response.send_message(
                embed=error_embed("Only staff need to respond to activity checks."),
                ephemeral=True,
            )
            return

        first = await self.cog.bot.db.record_activity(check_id, interaction.user.id)
        if not first:
            await interaction.response.send_message(
                embed=base_embed("✅ Already recorded", "You're marked active.", accent=BLUE),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=base_embed(
                "✅ Marked active",
                f"Recorded <t:{int(time.time())}:R>. Thanks!",
                accent=BLUE,
            ),
            ephemeral=True,
        )
        await self.cog.refresh_activity(check)


class LegitView(discord.ui.View):
    """Legit / not legit voting, tallied in the database."""

    def __init__(self, cog: "Staff", vote_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        if vote_id is not None:
            self.legit.custom_id = f"{LEGIT_YES}:{vote_id}"
            self.not_legit.custom_id = f"{LEGIT_NO}:{vote_id}"

    @staticmethod
    def vote_id_from(interaction: discord.Interaction) -> int | None:
        parts = (interaction.data or {}).get("custom_id", "").split(":")
        return int(parts[-1]) if parts and parts[-1].isdigit() else None

    async def _vote(self, interaction: discord.Interaction, choice: str):
        vote_id = self.vote_id_from(interaction)
        if vote_id is None:
            await interaction.response.send_message(
                embed=error_embed("This vote is missing its id."), ephemeral=True
            )
            return

        vote = await self.cog.bot.db.get_legit_vote(vote_id)
        if vote is None or vote["closed"]:
            await interaction.response.send_message(
                embed=error_embed("This vote is closed."), ephemeral=True
            )
            return

        result = await self.cog.bot.db.cast_legit_vote(vote_id, interaction.user.id, choice)
        wording = {
            "new": "Vote recorded.",
            "changed": "Vote changed.",
            "same": "You already voted that way.",
        }[result]
        await interaction.response.send_message(
            embed=base_embed("🗳️ " + wording, accent=BLUE), ephemeral=True
        )
        if result != "same":
            await self.cog.refresh_legit(vote)

    @discord.ui.button(
        label="Legit", emoji="✅", style=discord.ButtonStyle.success, custom_id=LEGIT_YES
    )
    async def legit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._vote(interaction, "legit")

    @discord.ui.button(
        label="Not legit", emoji="❌", style=discord.ButtonStyle.danger, custom_id=LEGIT_NO
    )
    async def not_legit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._vote(interaction, "not_legit")


class Staff(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.activity_loop.start()

    async def cog_unload(self):
        self.activity_loop.cancel()

    async def cog_load(self):
        self.bot.add_view(ActivityView(self))
        self.bot.add_view(LegitView(self))
        try:
            for check in await self.bot.db.open_activity_checks():
                if check["message_id"]:
                    self.bot.add_view(
                        ActivityView(self, check["id"]), message_id=check["message_id"]
                    )
            for vote in await self.bot.db.open_legit_votes():
                if vote["message_id"]:
                    self.bot.add_view(
                        LegitView(self, vote["id"]), message_id=vote["message_id"]
                    )
        except Exception:
            log.exception("Couldn't restore staff views")

    # ------------------------------------------------------------ helpers

    async def staff_members(self, guild: discord.Guild) -> list[discord.Member]:
        roles = await staff_role_objects(self.bot, guild)
        members: dict[int, discord.Member] = {}
        for role in roles:
            for member in role.members:
                if not member.bot:
                    members[member.id] = member
        return list(members.values())

    async def refresh_activity(self, check: dict) -> None:
        channel = self.bot.get_channel(check["channel_id"])
        if channel is None or not check["message_id"]:
            return
        responders = await self.bot.db.activity_responders(check["id"])
        try:
            message = await channel.fetch_message(check["message_id"])
            embed = message.embeds[0] if message.embeds else None
            if embed is None:
                return
            embed.set_field_at(
                0, name="Responded", value=str(len(responders)), inline=True
            )
            await message.edit(embed=embed)
        except discord.HTTPException:
            pass

    async def refresh_legit(self, vote: dict) -> None:
        channel = self.bot.get_channel(vote["channel_id"])
        if channel is None or not vote["message_id"]:
            return
        tally = await self.bot.db.legit_tally(vote["id"])
        try:
            message = await channel.fetch_message(vote["message_id"])
            embed = message.embeds[0] if message.embeds else None
            if embed is None:
                return
            embed.set_field_at(0, name="✅ Legit", value=str(tally["legit"]), inline=True)
            embed.set_field_at(
                1, name="❌ Not legit", value=str(tally["not_legit"]), inline=True
            )
            await message.edit(embed=embed)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------- staff roles

    roles_group = app_commands.Group(
        name="staffroles",
        description="Choose which roles count as staff",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @roles_group.command(name="add", description="Add a staff role")
    async def roles_add(self, interaction: discord.Interaction, role: discord.Role):
        current = await self.bot.db.staff_role_ids(interaction.guild_id)
        if role.id in current:
            await interaction.response.send_message(
                embed=error_embed(f"{role.mention} is already a staff role."),
                ephemeral=True,
            )
            return

        current.append(role.id)
        await self.bot.db.set_staff_roles(interaction.guild_id, current)
        await interaction.response.send_message(
            embed=base_embed(
                "✅ Staff role added",
                f"{role.mention} can now see every ticket, run giveaways, and will "
                "be included in activity checks.\n\n*Existing ticket channels aren't "
                "changed — run `/ticketsync` to add them to open tickets.*",
            )
        )

    @roles_group.command(name="remove", description="Remove a staff role")
    async def roles_remove(self, interaction: discord.Interaction, role: discord.Role):
        current = await self.bot.db.staff_role_ids(interaction.guild_id)
        if role.id not in current:
            await interaction.response.send_message(
                embed=error_embed(f"{role.mention} isn't a staff role."), ephemeral=True
            )
            return

        current.remove(role.id)
        await self.bot.db.set_staff_roles(interaction.guild_id, current)
        await interaction.response.send_message(
            embed=base_embed("✅ Staff role removed", f"{role.mention} removed.", accent=PINK)
        )

    @roles_group.command(name="list", description="Show the staff roles")
    async def roles_list(self, interaction: discord.Interaction):
        roles = await staff_role_objects(self.bot, interaction.guild)
        configured = await self.bot.db.staff_role_ids(interaction.guild_id)

        embed = base_embed("🛡️ Staff roles")
        if roles:
            embed.description = "\n".join(
                f"{r.mention} — {len(r.members)} member(s)"
                + ("" if r.id in configured else " *(from a ticket type)*")
                for r in roles
            )
        else:
            embed.description = (
                "None set. Add one with `/staffroles add` — until then only "
                "members with Manage Server count as staff."
            )
        await interaction.response.send_message(embed=embed)

    # ---------------------------------------------------- activity checks

    @app_commands.command(
        name="activitycheck", description="Ping staff to confirm they're active"
    )
    @app_commands.describe(
        hours="How long staff have to respond",
        channel="Where to post it (defaults to here)",
        strike="Give a strike to anyone who misses it",
    )
    @staff_only()
    @app_commands.guild_only()
    async def activitycheck(
        self,
        interaction: discord.Interaction,
        hours: app_commands.Range[int, 1, 168] = 24,
        channel: discord.TextChannel | None = None,
        strike: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)
        target = channel or interaction.channel

        staff = await self.staff_members(interaction.guild)
        if not staff:
            await interaction.followup.send(
                embed=error_embed(
                    "No staff roles configured — run `/staffroles add` first, "
                    "otherwise there's nobody to check."
                )
            )
            return

        deadline = time.time() + hours * 3600
        check_id = await self.bot.db.create_activity_check(
            interaction.guild_id, target.id, interaction.user.id, deadline, strike
        )

        embed = base_embed(
            "📋 Staff activity check",
            f"Every staff member must press the button below before "
            f"<t:{int(deadline)}:F> (<t:{int(deadline)}:R>).",
            accent=YELLOW,
        )
        embed.add_field(name="Responded", value="0", inline=True)
        embed.add_field(name="Staff", value=str(len(staff)), inline=True)
        embed.add_field(
            name="Miss it and",
            value="you get a strike" if strike else "nothing happens (no strikes)",
            inline=True,
        )
        embed.set_footer(text=f"Activity check #{check_id} • DonutDuck")

        roles = await staff_role_objects(self.bot, interaction.guild)
        mentions = " ".join(r.mention for r in roles)

        try:
            message = await target.send(
                content=mentions,
                embed=embed,
                view=ActivityView(self, check_id),
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(f"I can't post in {target.mention}.")
            )
            return

        await self.bot.db.set_activity_message(check_id, message.id)
        self.bot.add_view(ActivityView(self, check_id), message_id=message.id)

        await interaction.followup.send(
            embed=base_embed(
                "✅ Activity check started",
                f"#{check_id} posted in {target.mention}, closing <t:{int(deadline)}:R>.",
            )
        )

    @tasks.loop(minutes=2)
    async def activity_loop(self):
        try:
            due = await self.bot.db.due_activity_checks()
        except Exception:
            log.exception("Couldn't read activity checks")
            return

        for check in due:
            try:
                await self.close_activity(check)
            except Exception:
                log.exception("Failed to close activity check %s", check["id"])

    @activity_loop.before_loop
    async def before_activity(self):
        await self.bot.wait_until_ready()

    async def close_activity(self, check: dict) -> None:
        if not await self.bot.db.close_activity_check(check["id"]):
            return

        guild = self.bot.get_guild(check["guild_id"])
        channel = self.bot.get_channel(check["channel_id"])
        if guild is None or channel is None:
            return

        responders = set(await self.bot.db.activity_responders(check["id"]))
        staff = await self.staff_members(guild)
        missed = [m for m in staff if m.id not in responders]

        # Read from the row, not memory — a check can outlive a restart.
        give_strikes = bool(check.get("strike_on_miss", 1))

        struck = []
        if give_strikes:
            settings = await self.bot.db.settings(guild.id)
            limit = settings.get("strike_limit", 3)
            for member in missed:
                await self.bot.db.add_strike(
                    guild.id,
                    member.id,
                    f"Missed activity check #{check['id']}",
                    check_id=check["id"],
                )
                count = await self.bot.db.strike_count(guild.id, member.id)
                struck.append((member, count, limit))

        embed = base_embed(
            f"📋 Activity check #{check['id']} closed",
            accent=PINK if missed else BLUE,
        )
        embed.add_field(
            name="Responded", value=f"{len(responders)}/{len(staff)}", inline=True
        )
        embed.add_field(name="Missed", value=str(len(missed)), inline=True)

        if missed:
            embed.add_field(
                name="Didn't respond",
                value=" ".join(m.mention for m in missed)[:1024],
                inline=False,
            )
        if struck:
            embed.add_field(
                name="Strikes given",
                value="\n".join(
                    f"{m.mention} — **{c}**/{limit}"
                    + ("  ⚠️ **at the limit**" if c >= limit else "")
                    for m, c, limit in struck
                )[:1024],
                inline=False,
            )

        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

        if check["message_id"]:
            try:
                message = await channel.fetch_message(check["message_id"])
                closed_view = ActivityView(self, check["id"])
                for child in closed_view.children:
                    child.disabled = True
                await message.edit(view=closed_view)
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------ strikes

    @app_commands.command(name="strikes", description="See someone's strikes")
    @app_commands.describe(member="Whose strikes (defaults to you)")
    @app_commands.guild_only()
    async def strikes(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        member = member or interaction.user
        rows = await self.bot.db.strikes_for(interaction.guild_id, member.id)
        settings = await self.bot.db.settings(interaction.guild_id)
        limit = settings.get("strike_limit", 3)

        embed = base_embed(
            f"⚠️ Strikes — {member.display_name}",
            accent=PINK if len(rows) >= limit else BLUE,
        )
        embed.add_field(name="Active", value=f"{len(rows)}/{limit}", inline=True)
        if rows:
            embed.add_field(
                name="History",
                value="\n".join(
                    f"**#{r['id']}** <t:{int(r['created_at'])}:R> — {r['reason'] or 'no reason'}"
                    for r in rows[:10]
                )[:1024],
                inline=False,
            )
        else:
            embed.description = "Clean record."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="strike", description="Give someone a strike")
    @app_commands.describe(member="Who", reason="Why")
    @staff_only()
    @app_commands.guild_only()
    async def strike(
        self, interaction: discord.Interaction, member: discord.Member, reason: str
    ):
        strike_id = await self.bot.db.add_strike(
            interaction.guild_id, member.id, reason, issued_by=interaction.user.id
        )
        count = await self.bot.db.strike_count(interaction.guild_id, member.id)
        settings = await self.bot.db.settings(interaction.guild_id)
        limit = settings.get("strike_limit", 3)

        embed = base_embed(
            "⚠️ Strike given",
            f"{member.mention} now has **{count}**/{limit} strikes.",
            accent=PINK,
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Strike #{strike_id} • clear with /strikeclear")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="strikeclear", description="Clear strikes")
    @app_commands.describe(
        member="Whose strikes to clear", strike_id="One specific strike (blank = all)"
    )
    @staff_only()
    @app_commands.guild_only()
    async def strikeclear(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        strike_id: int | None = None,
    ):
        if strike_id is not None:
            ok = await self.bot.db.clear_strike(interaction.guild_id, strike_id)
            await interaction.response.send_message(
                embed=base_embed("✅ Strike cleared", f"#{strike_id} removed.")
                if ok
                else error_embed(f"No active strike #{strike_id}."),
                ephemeral=not ok,
            )
            return

        cleared = await self.bot.db.clear_all_strikes(interaction.guild_id, member.id)
        await interaction.response.send_message(
            embed=base_embed(
                "✅ Strikes cleared",
                f"Removed **{cleared}** strike(s) from {member.mention}.",
            )
        )

    @app_commands.command(name="strikelist", description="Everyone with strikes")
    @staff_only()
    @app_commands.guild_only()
    async def strikelist(self, interaction: discord.Interaction):
        rows = await self.bot.db.strike_leaderboard(interaction.guild_id)
        settings = await self.bot.db.settings(interaction.guild_id)
        limit = settings.get("strike_limit", 3)

        if not rows:
            await interaction.response.send_message(
                embed=base_embed("⚠️ No strikes", "Everyone's clean.")
            )
            return

        embed = base_embed(f"⚠️ Strikes — {len(rows)} member(s)", accent=YELLOW)
        embed.description = "\n".join(
            f"<@{r['user_id']}> — **{r['count']}**/{limit}"
            + ("  ⚠️" if r["count"] >= limit else "")
            for r in rows[:25]
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="strikelimit", description="Strikes before it's flagged")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def strikelimit(
        self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20]
    ):
        await self.bot.db.set_settings(interaction.guild_id, strike_limit=limit)
        await interaction.response.send_message(
            embed=base_embed("✅ Strike limit set", f"Flagged at **{limit}** strikes.")
        )

    # -------------------------------------------------------- legit votes

    @app_commands.command(
        name="legit", description="Post a legit check to the voting channel"
    )
    @app_commands.describe(
        member="Who's being vouched for (e.g. the giveaway host or winner)",
        prize="What was given away",
        giveaway_id="Link it to a giveaway",
        channel="Override the voting channel",
    )
    @staff_only()
    @app_commands.guild_only()
    async def legit(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        prize: str | None = None,
        giveaway_id: int | None = None,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        settings = await self.bot.db.settings(interaction.guild_id)
        target = channel or interaction.guild.get_channel(settings.get("legit_channel") or 0)
        if target is None:
            await interaction.followup.send(
                embed=error_embed(
                    "No voting channel set. Use `/legitchannel` or pass `channel:`."
                )
            )
            return

        giveaway = None
        if giveaway_id:
            giveaway = await self.bot.db.get_giveaway(giveaway_id)
            if giveaway is None or giveaway["guild_id"] != interaction.guild_id:
                await interaction.followup.send(
                    embed=error_embed(f"No giveaway with ID `{giveaway_id}`.")
                )
                return
            prize = prize or giveaway["prize"]
            if member is None:
                member = interaction.guild.get_member(giveaway["host_id"])

        vote_id = await self.bot.db.create_legit_vote(
            interaction.guild_id,
            target.id,
            giveaway_id,
            member.id if member else None,
            prize,
        )

        embed = base_embed("🗳️ Are we legit?", accent=YELLOW)
        embed.add_field(name="✅ Legit", value="0", inline=True)
        embed.add_field(name="❌ Not legit", value="0", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        if member:
            embed.add_field(name="Host / winner", value=member.mention, inline=True)
        if prize:
            embed.add_field(name="Prize", value=prize, inline=True)
        if giveaway_id:
            embed.add_field(name="Giveaway", value=f"`#{giveaway_id}`", inline=True)
        embed.description = (
            "Did you receive what you won, or see it paid out? Vote below — "
            "results are recorded automatically."
        )
        embed.set_footer(text=f"Legit vote #{vote_id} • one vote each, changeable")

        try:
            message = await target.send(embed=embed, view=LegitView(self, vote_id))
        except discord.Forbidden:
            await interaction.followup.send(
                embed=error_embed(f"I can't post in {target.mention}.")
            )
            return

        await self.bot.db.set_legit_message(vote_id, message.id)
        self.bot.add_view(LegitView(self, vote_id), message_id=message.id)
        await interaction.followup.send(
            embed=base_embed("✅ Legit check posted", f"Vote #{vote_id} in {target.mention}.")
        )

    @app_commands.command(name="legitresults", description="Results of a legit vote")
    @app_commands.describe(vote_id="Which vote")
    @app_commands.guild_only()
    async def legitresults(self, interaction: discord.Interaction, vote_id: int):
        await interaction.response.defer()
        vote = await self.bot.db.get_legit_vote(vote_id)
        if vote is None or vote["guild_id"] != interaction.guild_id:
            await interaction.followup.send(
                embed=error_embed(f"No legit vote #{vote_id}.")
            )
            return

        tally = await self.bot.db.legit_tally(vote_id)
        total = tally["legit"] + tally["not_legit"]
        pct = (tally["legit"] / total * 100) if total else 0

        embed = base_embed(f"🗳️ Legit vote #{vote_id}", accent=YELLOW)
        embed.add_field(name="✅ Legit", value=str(tally["legit"]), inline=True)
        embed.add_field(name="❌ Not legit", value=str(tally["not_legit"]), inline=True)
        embed.add_field(name="Score", value=f"{pct:.0f}% legit" if total else "no votes", inline=True)
        if vote["prize"]:
            embed.add_field(name="Prize", value=vote["prize"], inline=True)
        if vote["subject_id"]:
            embed.add_field(name="Subject", value=f"<@{vote['subject_id']}>", inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="legitchannel", description="Set the legit voting channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def legitchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        await self.bot.db.set_settings(interaction.guild_id, legit_channel=channel.id)
        await interaction.response.send_message(
            embed=base_embed("✅ Legit channel set", f"Votes post to {channel.mention}.")
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Staff(bot))
