"""Giveaways.

Entries live in the database rather than in reactions, so the count survives
restarts and can't be inflated by someone removing and re-adding a reaction.
Each giveaway's entry button carries its own custom_id; on startup the cog
re-registers a persistent view per active giveaway so old messages keep
working after a redeploy.

When a giveaway ends, every winner automatically gets a private claim ticket
opened for them via the ticket cog's `giveaway-claim` type.
"""

from __future__ import annotations

import logging
import random
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..games import (
    GAMBLE,
    KEEP,
    format_value,
    next_double,
    parse_value,
    MODE_BLURBS,
    MODE_LABELS,
    SPLIT,
    STEAL,
    resolve_split_steal,
)
from ..permissions import staff_only
from ..theme import BLUE, PINK, YELLOW
from ..permissions import staff_overwrites
from ..utils import base_embed, error_embed, resolve_member

log = logging.getLogger("donutduck.giveaways")

ENTER_PREFIX = "dd:gw:enter:"
CLAIM_PREFIX = "dd:gw:claim:"
CLAIM_TYPE = "giveaway-claim"

DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> int | None:
    """'2h30m' or '3d' -> seconds. None if nothing parsed."""
    matches = DURATION_RE.findall(text or "")
    if not matches:
        return None
    total = sum(int(amount) * UNIT_SECONDS[unit.lower()] for amount, unit in matches)
    return total or None


def giveaway_embed(
    giveaway: dict, entries: int, *, ended: bool = False, winners: list[int] | None = None
) -> discord.Embed:
    if ended:
        if winners:
            body = "**Winners:** " + ", ".join(f"<@{w}>" for w in winners)
        else:
            body = "No valid entries — nobody won."
        embed = base_embed(f"🎉 {giveaway['prize']}", body, accent=PINK)
        embed.add_field(name="Ended", value=f"<t:{int(giveaway['ends_at'])}:R>", inline=True)
    else:
        embed = base_embed(f"🎉 {giveaway['prize']}", giveaway.get("description"), accent=YELLOW)
        embed.add_field(
            name="Ends", value=f"<t:{int(giveaway['ends_at'])}:R>", inline=True
        )

    embed.add_field(name="Entries", value=str(entries), inline=True)
    embed.add_field(
        name="Winners", value=str(giveaway["winner_count"]), inline=True
    )
    embed.add_field(name="Host", value=f"<@{giveaway['host_id']}>", inline=True)
    if giveaway.get("mode", "normal") != "normal":
        embed.add_field(
            name="Mode", value=MODE_LABELS.get(giveaway["mode"], giveaway["mode"]), inline=True
        )
    if giveaway.get("required_role"):
        embed.add_field(
            name="Requirement", value=f"<@&{giveaway['required_role']}>", inline=True
        )
    embed.set_footer(
        text="Winners press Claim to open a ticket • DonutDuck"
        if not ended
        else "DonutDuck giveaways"
    )
    return embed


class GiveawayView(discord.ui.View):
    """One per giveaway; custom_id carries the id so it survives restarts."""

    def __init__(self, cog: "Giveaways", giveaway_id: int, disabled: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id

        button = discord.ui.Button(
            label="Enter",
            emoji="🎉",
            style=discord.ButtonStyle.primary,
            custom_id=f"{ENTER_PREFIX}{giveaway_id}",
            disabled=disabled,
        )
        button.callback = self.enter
        self.add_item(button)

    async def enter(self, interaction: discord.Interaction):
        db = self.cog.bot.db
        giveaway = await db.get_giveaway(self.giveaway_id)

        if not giveaway or giveaway["ended"]:
            await interaction.response.send_message(
                embed=error_embed("This giveaway has already ended."), ephemeral=True
            )
            return

        if giveaway["required_role"]:
            if not any(r.id == giveaway["required_role"] for r in interaction.user.roles):
                await interaction.response.send_message(
                    embed=error_embed(
                        f"You need <@&{giveaway['required_role']}> to enter this one."
                    ),
                    ephemeral=True,
                )
                return

        # Rejecting at entry rather than at the draw is kinder: the person
        # finds out now instead of thinking they were in the running.
        min_days = giveaway.get("min_account_days") or 0
        if min_days:
            age = (discord.utils.utcnow() - interaction.user.created_at).days
            if age < min_days:
                await interaction.response.send_message(
                    embed=error_embed(
                        f"This giveaway needs a Discord account at least "
                        f"**{min_days}** days old. Yours is {age}."
                    ),
                    ephemeral=True,
                )
                return

        # Second press leaves the giveaway, so the button toggles.
        if await db.add_entry(self.giveaway_id, interaction.user.id):
            count = await db.entry_count(self.giveaway_id)
            await interaction.response.send_message(
                embed=base_embed(
                    "🎉 You're in",
                    f"Entered **{giveaway['prize']}**. Press again to leave.\n"
                    f"Entries so far: **{count}**",
                    accent=YELLOW,
                ),
                ephemeral=True,
            )
        else:
            await db.remove_entry(self.giveaway_id, interaction.user.id)
            count = await db.entry_count(self.giveaway_id)
            await interaction.response.send_message(
                embed=base_embed(
                    "Left the giveaway",
                    f"You're no longer entered. Entries: **{count}**",
                    accent=BLUE,
                ),
                ephemeral=True,
            )

        # Queued rather than edited now, so a rush of entries can't stall the
        # button.
        self.cog.mark_dirty(self.giveaway_id)


class SplitStealView(discord.ui.View):
    """Shown privately to each of the two winners. Choices stay hidden until
    both are in, so neither can react to the other."""

    def __init__(self, cog: "Giveaways", giveaway: dict):
        super().__init__(timeout=600)
        self.cog = cog
        self.giveaway = giveaway

    async def _choose(self, interaction: discord.Interaction, choice: str):
        stored = await self.cog.bot.db.set_winner_choice(
            self.giveaway["id"], interaction.user.id, choice
        )
        if not stored:
            await interaction.response.send_message(
                embed=error_embed("You've already locked in a choice."), ephemeral=True
            )
            return

        await interaction.response.edit_message(
            embed=base_embed(
                "🤝 Locked in",
                f"You chose **{choice}**. Waiting for the other winner…",
                accent=BLUE,
            ),
            view=None,
        )
        await self.cog.try_resolve_split_steal(self.giveaway)

    @discord.ui.button(label="Split", style=discord.ButtonStyle.success, emoji="🤝")
    async def split(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._choose(interaction, SPLIT)

    @discord.ui.button(label="Steal", style=discord.ButtonStyle.danger, emoji="🔪")
    async def steal(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._choose(interaction, STEAL)


class DoubleOrKeepView(discord.ui.View):
    """Keep the prize and claim it, or double it into a brand-new giveaway.

    Quacko's objection was right: a prize is free text, so "double" is
    meaningless without a number. The host can set `value:` when starting the
    giveaway; otherwise it's read from the prize name ("$5m"). If neither
    yields a number, the double button isn't offered at all rather than
    guessing.
    """

    def __init__(self, cog: "Giveaways", giveaway: dict, value: float | None):
        super().__init__(timeout=600)
        self.cog = cog
        self.giveaway = giveaway
        self.value = value
        if value is None:
            self.remove_item(self.double)

    @discord.ui.button(label="Keep prize", style=discord.ButtonStyle.success, emoji="✅")
    async def keep(self, interaction: discord.Interaction, _: discord.ui.Button):
        stored = await self.cog.bot.db.set_winner_choice(
            self.giveaway["id"], interaction.user.id, KEEP
        )
        if not stored:
            await interaction.response.send_message(
                embed=error_embed("You've already decided."), ephemeral=True
            )
            return

        await self.cog.bot.db.resolve_winner(
            self.giveaway["id"], interaction.user.id, self.giveaway["prize"]
        )
        await interaction.response.edit_message(
            embed=base_embed(
                "✅ Prize kept",
                "Opening your claim ticket now.",
                accent=BLUE,
            ),
            view=None,
        )
        channel = await self.cog.open_claim_ticket(self.giveaway, interaction.user.id)
        if channel:
            await interaction.followup.send(
                embed=base_embed("🎁 Claim ticket", channel.mention, accent=YELLOW),
                ephemeral=True,
            )

    @discord.ui.button(label="Double it", style=discord.ButtonStyle.danger, emoji="🎲")
    async def double(self, interaction: discord.Interaction, _: discord.ui.Button):
        settings = await self.cog.bot.db.settings(interaction.guild_id)
        cap = settings.get("giveaway_cap")
        doubled, note = next_double(
            self.value, cap, self.giveaway.get("double_count", 0)
        )

        if doubled is None:
            await interaction.response.send_message(
                embed=error_embed(
                    f"{note}\n\nPress **Keep prize** to claim "
                    f"{format_value(self.value)} instead."
                ),
                ephemeral=True,
            )
            return

        stored = await self.cog.bot.db.set_winner_choice(
            self.giveaway["id"], interaction.user.id, GAMBLE
        )
        if not stored:
            await interaction.response.send_message(
                embed=error_embed("You've already decided."), ephemeral=True
            )
            return

        # The winner gives up this prize; a new giveaway worth double is run
        # in its place, open to everyone.
        await self.cog.bot.db.resolve_winner(
            self.giveaway["id"], interaction.user.id, None
        )
        await self.cog.bot.db.mark_claimed(
            self.giveaway["id"], interaction.user.id, None
        )

        await interaction.response.edit_message(
            embed=base_embed(
                "🎲 Doubled",
                f"{note}\nA new giveaway is starting — you'll need to enter it "
                "like everyone else.",
                accent=YELLOW,
            ),
            view=None,
        )
        await self.cog.launch_doubled(self.giveaway, doubled, interaction.user)


class IGNModal(discord.ui.Modal, title="Claim your prize"):
    ign = discord.ui.TextInput(
        label="Your Minecraft IGN",
        placeholder="Exactly as it appears in game",
        required=True,
        max_length=32,
    )

    def __init__(self, cog: "Giveaways", giveaway: dict):
        super().__init__()
        self.cog = cog
        self.giveaway = giveaway

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = await self.cog.open_claim_ticket(
            self.giveaway, interaction.user.id, ign=self.ign.value.strip()
        )
        if channel:
            await interaction.followup.send(
                embed=base_embed(
                    "🎁 Claimed",
                    f"Your claim ticket is open: {channel.mention}",
                    accent=YELLOW,
                ),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=error_embed(
                    "I couldn't open a claim ticket — ask staff to check "
                    "`/ticketsetup` has been run."
                ),
                ephemeral=True,
            )


class ClaimView(discord.ui.View):
    """Posted publicly after a giveaway ends. Only winners can press it, and
    pressing it is what opens the ticket — no more channels appearing for
    people who never came back."""

    def __init__(self, cog: "Giveaways", giveaway_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id

        button = discord.ui.Button(
            label="Claim prize",
            emoji="🎁",
            style=discord.ButtonStyle.success,
            custom_id=f"{CLAIM_PREFIX}{giveaway_id}",
        )
        button.callback = self.claim
        self.add_item(button)

    async def claim(self, interaction: discord.Interaction):
        db = self.cog.bot.db
        giveaway = await db.get_giveaway(self.giveaway_id)
        if giveaway is None:
            await interaction.response.send_message(
                embed=error_embed("That giveaway no longer exists."), ephemeral=True
            )
            return

        row = await db.winner_row(self.giveaway_id, interaction.user.id)
        if row is None:
            await interaction.response.send_message(
                embed=error_embed("You're not a winner of this giveaway."), ephemeral=True
            )
            return
        if row["expired"]:
            await interaction.response.send_message(
                embed=error_embed(
                    "The claim window for this prize has closed. Ask the host "
                    "whether it can be rerolled."
                ),
                ephemeral=True,
            )
            return
        if row["claimed"]:
            where = f" (<#{row['ticket_id']}>)" if row["ticket_id"] else ""
            await interaction.response.send_message(
                embed=error_embed(f"You've already claimed this prize{where}."),
                ephemeral=True,
            )
            return

        mode = giveaway.get("mode", "normal")

        if mode == "split_steal":
            if row["choice"]:
                await interaction.response.send_message(
                    embed=base_embed(
                        "🤝 Already chosen",
                        f"You picked **{row['choice']}**. Waiting on the other winner.",
                        accent=BLUE,
                    ),
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                embed=base_embed(
                    "🤝 Split or Steal",
                    f"**{giveaway['prize']}** is on the line.\n\n"
                    "**Split** — if you both split, you share it.\n"
                    "**Steal** — if only you steal, you take it all.\n"
                    "If you *both* steal, neither of you gets anything.\n\n"
                    "Your choice is hidden until both of you have decided.",
                    accent=YELLOW,
                ),
                view=SplitStealView(self.cog, giveaway),
                ephemeral=True,
            )
            return

        if mode == "double":
            if row["resolved"]:
                await interaction.response.send_message(
                    embed=error_embed("You've already made your decision."), ephemeral=True
                )
                return

            value = giveaway.get("value") or parse_value(giveaway["prize"])
            body = f"You won **{giveaway['prize']}**.\n\n**Keep** it to claim now"
            if value:
                settings = await db.settings(interaction.guild_id)
                doubled, note = next_double(
                    value, settings.get("giveaway_cap"), giveaway.get("double_count", 0)
                )
                body += (
                    f", or **double it** — that starts a new giveaway worth "
                    f"{format_value(doubled)} that you'd have to win again."
                    if doubled
                    else f".\n\n*Doubling isn't available: {note}*"
                )
            else:
                body += (
                    ".\n\n*Doubling isn't available — this prize has no set "
                    "value, so there's nothing to double.*"
                )

            await interaction.response.send_message(
                embed=base_embed("🎲 Double or Keep", body, accent=YELLOW),
                view=DoubleOrKeepView(self.cog, giveaway, value),
                ephemeral=True,
            )
            return

        # Ask for the IGN up front so staff aren't chasing it in the ticket.
        await interaction.response.send_modal(IGNModal(self.cog, giveaway))


class DataTabs(discord.ui.View):
    """Tabbed browser over a server's giveaway history.

    Tabs are buttons rather than a select so the current one can be
    highlighted — with a dropdown you can't see where you are at a glance.
    """

    TABS = ("overview", "active", "ended", "winners", "unclaimed")
    LABELS = {
        "overview": "📊 Overview",
        "active": "🎉 Running",
        "ended": "🏁 Ended",
        "winners": "🏆 Winners",
        "unclaimed": "⌛ Unclaimed",
    }

    def __init__(self, cog: "Giveaways", guild_id: int, owner_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.tab = "overview"
        self.page = 0
        self.message: discord.Message | None = None

        for key in self.TABS:
            button = discord.ui.Button(
                label=self.LABELS[key],
                style=discord.ButtonStyle.primary
                if key == self.tab
                else discord.ButtonStyle.secondary,
                custom_id=f"tab:{key}",
                row=0 if key in ("overview", "active", "ended") else 1,
            )
            button.callback = self._make_callback(key)
            self.add_item(button)

    def _make_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.tab = key
            self.page = 0
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.custom_id:
                    if child.custom_id.startswith("tab:"):
                        child.style = (
                            discord.ButtonStyle.primary
                            if child.custom_id == f"tab:{key}"
                            else discord.ButtonStyle.secondary
                        )
            await interaction.response.edit_message(embed=await self.build(), view=self)

        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Run `/giveaway getdata` yourself to browse this.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def build(self) -> discord.Embed:
        db = self.cog.bot.db
        everything = await db.all_giveaways(self.guild_id)
        active = [g for g in everything if not g["ended"]]
        ended = [g for g in everything if g["ended"] and not g.get("cancelled")]
        cancelled = [g for g in everything if g.get("cancelled")]

        if self.tab == "overview":
            embed = base_embed("📊 Giveaway data", accent=BLUE)
            total_entries = 0
            for giveaway in everything:
                total_entries += await db.entry_count(giveaway["id"])
            winners = await db.all_winners(self.guild_id)
            claimed = [w for w in winners if w["claimed"]]
            expired = [w for w in winners if w["expired"]]

            embed.add_field(name="Total giveaways", value=str(len(everything)), inline=True)
            embed.add_field(name="Running", value=str(len(active)), inline=True)
            embed.add_field(name="Ended", value=str(len(ended)), inline=True)
            embed.add_field(name="Cancelled", value=str(len(cancelled)), inline=True)
            embed.add_field(name="Total entries", value=f"{total_entries:,}", inline=True)
            embed.add_field(name="Winners drawn", value=str(len(winners)), inline=True)
            embed.add_field(
                name="Claimed",
                value=f"{len(claimed)}/{len(winners)}" if winners else "—",
                inline=True,
            )
            embed.add_field(name="Expired unclaimed", value=str(len(expired)), inline=True)

            if everything:
                modes: dict[str, int] = {}
                for giveaway in everything:
                    mode = giveaway.get("mode", "normal")
                    modes[mode] = modes.get(mode, 0) + 1
                embed.add_field(
                    name="Modes used",
                    value="\n".join(
                        f"{MODE_LABELS.get(m, m)}: {n}" for m, n in modes.items()
                    ),
                    inline=False,
                )
            embed.set_footer(text="Pick a tab below for the detail")
            return embed

        if self.tab in ("active", "ended"):
            rows = active if self.tab == "active" else ended
            rows = sorted(rows, key=lambda g: g["created_at"], reverse=True)
            embed = base_embed(
                f"{self.LABELS[self.tab]} — {len(rows)}",
                accent=YELLOW if self.tab == "active" else PINK,
            )
            if not rows:
                embed.description = "Nothing here yet."
                return embed

            for giveaway in rows[:10]:
                entries = await db.entry_count(giveaway["id"])
                when = (
                    f"ends <t:{int(giveaway['ends_at'])}:R>"
                    if self.tab == "active"
                    else f"ended <t:{int(giveaway['ends_at'])}:R>"
                )
                value = (
                    f"{when} · **{entries}** entries · {giveaway['winner_count']} winner(s)\n"
                    f"<#{giveaway['channel_id']}> · host <@{giveaway['host_id']}>"
                )
                if giveaway.get("mode", "normal") != "normal":
                    value += f" · {MODE_LABELS.get(giveaway['mode'])}"
                if giveaway.get("value"):
                    value += f" · worth {format_value(giveaway['value'])}"
                embed.add_field(
                    name=f"#{giveaway['id']} · {giveaway['prize'][:80]}",
                    value=value,
                    inline=False,
                )
            if len(rows) > 10:
                embed.set_footer(text=f"Showing 10 of {len(rows)}")
            return embed

        if self.tab == "winners":
            winners = await db.all_winners(self.guild_id)
            embed = base_embed(f"🏆 Winners — {len(winners)}", accent=YELLOW)
            if not winners:
                embed.description = "Nobody has won anything yet."
                return embed

            lines = []
            for row in winners[:15]:
                status = (
                    "✅ claimed"
                    if row["claimed"]
                    else ("⌛ expired" if row["expired"] else "🕓 waiting")
                )
                payout = row["payout"] or row["prize"]
                lines.append(
                    f"<@{row['user_id']}> — {payout[:40]} · {status} "
                    f"· <t:{int(row['won_at'])}:R>"
                )
            embed.description = "\n".join(lines)
            if len(winners) > 15:
                embed.set_footer(text=f"Showing 15 of {len(winners)}")
            return embed

        winners = await db.all_winners(self.guild_id)
        pending = [w for w in winners if not w["claimed"] and not w["expired"]]
        embed = base_embed(f"⌛ Unclaimed — {len(pending)}", accent=PINK)
        if not pending:
            embed.description = "Everything has been claimed."
            return embed
        embed.description = "\n".join(
            f"<@{w['user_id']}> — {(w['payout'] or w['prize'])[:40]} "
            f"· won <t:{int(w['won_at'])}:R> · giveaway `#{w['giveaway_id']}`"
            for w in pending[:15]
        )
        embed.set_footer(text="Host can redraw these with /giveaway reroll <id>")
        return embed


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._dirty: set[int] = set()
        self.giveaway_loop.start()
        self.refresh_loop.start()

    async def cog_unload(self):
        self.giveaway_loop.cancel()
        self.refresh_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """Re-attach a view to every still-running giveaway."""
        try:
            for giveaway in await self.bot.db.active_giveaways():
                if giveaway["message_id"]:
                    self.bot.add_view(
                        GiveawayView(self, giveaway["id"]),
                        message_id=giveaway["message_id"],
                    )
            # Ended giveaways with prizes still unclaimed need their Claim
            # button to keep working after a restart.
            for giveaway in await self.bot.db.unclaimed_giveaways():
                self.bot.add_view(ClaimView(self, giveaway["id"]))
        except Exception:
            log.exception("Couldn't restore giveaway views")

    # ----------------------------------------------------------- internals

    def mark_dirty(self, giveaway_id: int) -> None:
        """Queue an entry-count refresh instead of editing immediately.

        Editing on every button press cost two API calls per click (a fetch
        and an edit) against a limit of roughly five edits per five seconds
        per message. A burst of entries backed up behind that rate limiter,
        and because each click awaited the edit, interactions started missing
        Discord's 3-second acknowledgement window — which is why giveaways
        appeared to break once a few dozen people had entered.
        """
        self._dirty.add(giveaway_id)

    @tasks.loop(seconds=5)
    async def refresh_loop(self):
        if not self._dirty:
            return
        pending, self._dirty = self._dirty, set()

        for giveaway_id in pending:
            try:
                giveaway = await self.bot.db.get_giveaway(giveaway_id)
                if giveaway is None or giveaway["ended"]:
                    continue
                await self.refresh_message(giveaway)
            except Exception:
                log.exception("Couldn't refresh giveaway %s", giveaway_id)

    @refresh_loop.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    async def refresh_message(self, giveaway: dict) -> None:
        channel = self.bot.get_channel(giveaway["channel_id"])
        if channel is None or not giveaway["message_id"]:
            return
        try:
            # A partial message edits without fetching first — half the
            # requests, and the message body isn't needed anyway.
            message = channel.get_partial_message(giveaway["message_id"])
            count = await self.bot.db.entry_count(giveaway["id"])
            await message.edit(embed=giveaway_embed(giveaway, count))
        except discord.NotFound:
            log.info("Giveaway %s message is gone", giveaway["id"])
        except discord.HTTPException as exc:
            log.warning("Couldn't refresh giveaway %s: %s", giveaway["id"], exc)

    @tasks.loop(seconds=30)
    async def giveaway_loop(self):
        try:
            due = await self.bot.db.due_giveaways()
        except Exception:
            log.exception("Couldn't read due giveaways")
            return

        for giveaway in due:
            try:
                await self.end_giveaway(giveaway)
            except Exception:
                log.exception("Failed to end giveaway %s", giveaway["id"])

        try:
            await self.sweep_expired_claims()
        except Exception:
            log.exception("Claim expiry sweep failed")

    async def sweep_expired_claims(self) -> None:
        """Close the claim window on prizes nobody came back for."""
        for row in await self.bot.db.expired_claims():
            await self.bot.db.mark_expired(row["giveaway_id"], row["user_id"])
            channel = self.bot.get_channel(row["channel_id"])
            if channel is None:
                continue
            try:
                await channel.send(
                    embed=base_embed(
                        "⌛ Claim expired",
                        f"<@{row['user_id']}> didn't claim **{row['prize']}** within "
                        f"{row['claim_hours']} hour(s).\n"
                        f"Host can redraw with `/giveaway reroll {row['giveaway_id']}`.",
                        accent=PINK,
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

    @giveaway_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    async def pick_winners(
        self, giveaway: dict, count: int, exclude: set[int] | None = None
    ) -> list[int]:
        """Only members still in the server, and still holding the required
        role, are eligible — someone who left shouldn't win.

        Members are resolved with `resolve_member`, which falls back to a REST
        fetch when the cache misses. Without that fallback this returned zero
        winners on default intents, because the member cache is empty unless
        the privileged Members intent is on.

        The pool is shuffled first and resolved lazily, so a giveaway with 500
        entrants and 3 winners costs a handful of fetches, not 500.
        """
        entries = await self.bot.db.entries(giveaway["id"])
        guild = self.bot.get_guild(giveaway["guild_id"])
        if guild is None:
            return []

        exclude = exclude or set()
        pool = [user_id for user_id in entries if user_id not in exclude]
        random.shuffle(pool)

        min_days = giveaway.get("min_account_days") or 0
        bonus_role = giveaway.get("bonus_role")
        bonus_entries = max(1, giveaway.get("bonus_entries") or 1)
        now = discord.utils.utcnow()

        async def eligible(user_id: int):
            member = await resolve_member(guild, user_id)
            if member is None:
                log.debug("Entrant %s is no longer in guild %s", user_id, guild.id)
                return None
            if giveaway["required_role"] and not any(
                r.id == giveaway["required_role"] for r in member.roles
            ):
                return None
            if min_days and (now - member.created_at).days < min_days:
                log.debug("Entrant %s fails the account-age rule", user_id)
                return None
            return member

        winners: list[int] = []

        if bonus_role and bonus_entries > 1:
            # Weighted draw. This needs every candidate resolved up front, so
            # it's capped — an unweighted giveaway stays lazy and cheap.
            weighted: list[int] = []
            for user_id in pool[:300]:
                member = await eligible(user_id)
                if member is None:
                    continue
                tickets = (
                    bonus_entries
                    if any(r.id == bonus_role for r in member.roles)
                    else 1
                )
                weighted.extend([user_id] * tickets)

            random.shuffle(weighted)
            for user_id in weighted:
                if len(winners) >= count:
                    break
                if user_id not in winners:   # one prize per person
                    winners.append(user_id)
            if pool and not winners:
                log.warning("Giveaway %s had entries but no eligible winners", giveaway["id"])
            return winners

        checked = 0
        for user_id in pool:
            if len(winners) >= count:
                break
            # Safety valve so a giveaway full of departed members can't spin
            # through thousands of fetches.
            if checked >= max(count * 20, 100):
                break
            checked += 1

            if await eligible(user_id) is None:
                continue
            winners.append(user_id)

        if pool and not winners:
            log.warning(
                "Giveaway %s had %d entries but no eligible winners — check that "
                "entrants are still in the server and hold any required role.",
                giveaway["id"],
                len(pool),
            )
        return winners

    async def end_giveaway(self, giveaway: dict, announce: bool = True) -> list[int]:
        await self.bot.db.mark_giveaway_ended(giveaway["id"])
        winners = await self.pick_winners(giveaway, giveaway["winner_count"])
        if winners:
            await self.bot.db.record_winners(giveaway["id"], winners)

        channel = self.bot.get_channel(giveaway["channel_id"])
        count = await self.bot.db.entry_count(giveaway["id"])

        if channel and giveaway["message_id"]:
            try:
                message = await channel.fetch_message(giveaway["message_id"])
                await message.edit(
                    embed=giveaway_embed(giveaway, count, ended=True, winners=winners),
                    view=GiveawayView(self, giveaway["id"], disabled=True),
                )
            except discord.HTTPException:
                pass

        if channel and announce and not winners:
            await channel.send(
                embed=base_embed(
                    "🎉 Giveaway ended",
                    f"**{giveaway['prize']}** — no valid entries, so no winner.",
                    accent=PINK,
                )
            )

        if winners:
            await self.post_claim(giveaway, winners)
        return winners

    async def post_claim(
        self, giveaway: dict, winners: list[int], rerolled: bool = False
    ) -> None:
        """Announce winners and give them a button to claim with.

        Tickets are no longer opened automatically: a winner who never comes
        back would otherwise leave an empty channel behind, and for the
        minigame modes the claim press is also where the choice happens.
        """
        channel = self.bot.get_channel(giveaway["channel_id"])
        if channel is None:
            return

        mentions = ", ".join(f"<@{w}>" for w in winners)
        mode = giveaway.get("mode", "normal")
        hours = giveaway.get("claim_hours", 24)

        lines = [f"**{giveaway['prize']}**", "", f"Congratulations {mentions}!"]
        if mode != "normal":
            lines += ["", f"**{MODE_LABELS.get(mode, mode)}** — {MODE_BLURBS.get(mode, '')}"]
        lines += ["", "Press **Claim prize** below to continue."]
        if hours:
            lines.append(f"You have **{hours} hour(s)** to claim.")

        embed = base_embed(
            "🔄 Reroll" if rerolled else "🎉 Giveaway ended",
            "\n".join(lines),
            accent=YELLOW,
        )
        embed.set_footer(text="Only winners can press this button")

        try:
            message = await channel.send(
                content=mentions,
                embed=embed,
                view=ClaimView(self, giveaway["id"]),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            self.bot.add_view(ClaimView(self, giveaway["id"]), message_id=message.id)
        except discord.HTTPException:
            log.warning("Couldn't post claim message for giveaway %s", giveaway["id"])

    async def try_resolve_split_steal(self, giveaway: dict) -> None:
        """Reveal once both winners have chosen (or the window closed)."""
        rows = await self.bot.db.winners_full(giveaway["id"])
        active = [r for r in rows if not r["expired"]][:2]
        if len(active) < 2 or any(r["choice"] is None for r in active):
            return
        if any(r["resolved"] for r in active):
            return

        a, b = active
        payout_a, payout_b, summary = resolve_split_steal(
            giveaway["prize"], a["choice"], b["choice"]
        )
        await self.bot.db.resolve_winner(giveaway["id"], a["user_id"], payout_a)
        await self.bot.db.resolve_winner(giveaway["id"], b["user_id"], payout_b)

        channel = self.bot.get_channel(giveaway["channel_id"])
        if channel:
            embed = base_embed(
                "🤝 Split or Steal — results",
                f"**{giveaway['prize']}**\n\n{summary}",
                accent=YELLOW,
            )
            for row, payout in ((a, payout_a), (b, payout_b)):
                embed.add_field(
                    name=f"<@{row['user_id']}> chose {row['choice']}",
                    value=payout or "*nothing*",
                    inline=True,
                )
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

        for row, payout in ((a, payout_a), (b, payout_b)):
            if payout:
                await self.open_claim_ticket(giveaway, row["user_id"], payout=payout)
            else:
                await self.bot.db.mark_claimed(giveaway["id"], row["user_id"], None)

    async def launch_doubled(
        self, parent: dict, value: float, previous_winner: discord.Member
    ) -> None:
        """Start a fresh giveaway worth double the original."""
        channel = self.bot.get_channel(parent["channel_id"])
        if channel is None:
            return

        prize = f"{format_value(value)} (doubled)"
        duration = max(3600, int(parent["ends_at"] - parent["created_at"]))
        ends_at = time.time() + duration

        giveaway_id = await self.bot.db.create_giveaway(
            parent["guild_id"],
            parent["channel_id"],
            prize,
            parent["winner_count"],
            parent["host_id"],
            ends_at,
            description=(
                f"Doubled from **{parent['prize']}** after "
                f"{previous_winner.display_name} chose to double."
            ),
            required_role=parent["required_role"],
            mode="double",
            claim_hours=parent.get("claim_hours", 24),
            min_account_days=parent.get("min_account_days", 0),
            bonus_role=parent.get("bonus_role"),
            bonus_entries=parent.get("bonus_entries", 1),
            value=value,
            parent_id=parent["id"],
            double_count=parent.get("double_count", 0) + 1,
        )

        giveaway = await self.bot.db.get_giveaway(giveaway_id)
        message = await channel.send(
            content=f"🎲 {previous_winner.mention} doubled their prize!",
            embed=giveaway_embed(giveaway, 0),
            view=GiveawayView(self, giveaway_id),
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await self.bot.db.set_giveaway_message(giveaway_id, message.id)
        self.bot.add_view(GiveawayView(self, giveaway_id), message_id=message.id)
        log.info("Giveaway %s doubled into %s (%s)", parent["id"], giveaway_id, prize)

    async def open_claim_ticket(
        self,
        giveaway: dict,
        user_id: int,
        payout: str | None = None,
        ign: str | None = None,
    ):
        """Open the private claim ticket for a winner who pressed Claim."""
        tickets = self.bot.get_cog("Tickets")
        guild = self.bot.get_guild(giveaway["guild_id"])
        if tickets is None or guild is None:
            return None

        member = await resolve_member(guild, user_id)
        if member is None:
            log.warning(
                "Winner %s isn't resolvable in guild %s; no claim ticket opened",
                user_id,
                guild.id,
            )
            return None

        ticket_type = await self.bot.db.get_ticket_type(guild.id, CLAIM_TYPE)
        if not ticket_type or not ticket_type["enabled"]:
            log.info("Guild %s has no giveaway-claim type; skipping", guild.id)
            return None

        config = await self.bot.db.ticket_config(guild.id)
        category = guild.get_channel(ticket_type["category_id"] or config["category_id"] or 0)
        if not isinstance(category, discord.CategoryChannel):
            category = None

        number = await self.bot.db.next_ticket_number(guild.id)
        type_role = (
            guild.get_role(ticket_type["staff_role_id"])
            if ticket_type["staff_role_id"]
            else None
        )
        overwrites = await staff_overwrites(self.bot, guild, type_role)
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

        try:
            host = guild.get_member(giveaway["host_id"])
            host_name = host.display_name if host else "unknown host"
            # Channel name carries the winner and prize so staff can triage
            # from the sidebar; the topic spells out who hosted it.
            channel = await guild.create_text_channel(
                name=f"claim-{number:04d}-{member.display_name}"[:100],
                category=category,
                overwrites=overwrites,
                topic=(
                    f"Hosted by {host_name} · won {payout or giveaway['prize']} · "
                    f"winner {member}"
                )[:1024],
                reason=f"Giveaway {giveaway['id']} claim for {member}",
            )
        except discord.HTTPException:
            log.warning("Couldn't create claim ticket in guild %s", guild.id)
            return None

        claim_reason = f"Giveaway claim — {payout or giveaway['prize']}"
        ticket_id = await self.bot.db.create_ticket(
            guild.id,
            channel.id,
            number,
            CLAIM_TYPE,
            member.id,
            giveaway_id=giveaway["id"],
            reason=claim_reason,
        )
        await self.bot.db.link_winner_ticket(giveaway["id"], member.id, ticket_id)
        await self.bot.db.mark_claimed(giveaway["id"], member.id, ticket_id)
        if ign:
            await self.bot.db.set_ticket_ign(channel.id, ign)

        from .tickets import TicketControls, index_embed, open_embed

        staff_role = (
            guild.get_role(ticket_type["staff_role_id"])
            if ticket_type["staff_role_id"]
            else None
        )
        staff_mention = staff_role.mention if staff_role else ""

        if ticket_type.get("open_message") or ticket_type.get("open_title"):
            # Server has customised the giveaway-claim message; use theirs.
            embed = open_embed(
                ticket_type,
                number,
                member,
                claim_reason,
                None,
                guild,
                staff_mention,
            )
        else:
            embed = base_embed(
                f"🎁 {payout or giveaway['prize']} · from {host_name}",
                f"Congratulations {member.mention} — you won **{payout or giveaway['prize']}**!",
                accent=YELLOW,
            )
            embed.add_field(name="Prize", value=payout or giveaway["prize"], inline=True)
            embed.add_field(name="Host", value=f"<@{giveaway['host_id']}>", inline=True)
            embed.add_field(name="Ticket", value=f"#{number:04d}", inline=True)
            if ign:
                embed.add_field(name="IGN", value=f"`{ign}`", inline=True)
            embed.add_field(
                name="What now",
                value=(
                    "Post your Minecraft IGN here and staff will sort out delivery. "
                    "This ticket closes once the prize has been handed over."
                ),
                inline=False,
            )

        mentions = []
        if ticket_type.get("ping_user", 1):
            mentions.append(member.mention)
        if staff_role and ticket_type.get("ping_staff", 1):
            mentions.append(staff_role.mention)

        try:
            await channel.send(
                content=" ".join(mentions),
                embed=embed,
                view=TicketControls(tickets),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
            index = await channel.send(
                embed=index_embed(ticket_type, number, claim_reason, member)
            )
            await index.pin(reason="Ticket index")

        except discord.HTTPException:
            pass

        await tickets.log_event(
            guild,
            base_embed(
                "🎁 Claim ticket opened",
                f"**#{number:04d}** for {member.mention}\n"
                f"Prize: **{giveaway['prize']}** · {channel.mention}",
                accent=YELLOW,
            ),
        )
        return channel

    # ------------------------------------------------------------ commands

    # No default_permissions here on purpose: that hid the command from
    # everyone without Manage Server, which is what stopped staff running
    # giveaways. Access is enforced by staff_only() on each subcommand.
    group = app_commands.Group(
        name="giveaway", description="Run giveaways", guild_only=True
    )

    @group.command(name="start", description="Start a giveaway")
    @staff_only()
    @app_commands.describe(
        prize="What's being given away",
        duration="How long it runs, e.g. 30m, 2h, 3d, 1d12h",
        winners="How many winners to draw",
        description="Extra detail shown in the embed",
        required_role="Only members with this role can enter",
        channel="Where to post it (defaults to here)",
        mode="Normal, Split or Steal (needs exactly 2 winners), or Double or Nothing",
        claim_hours="Hours a winner has to press Claim (0 = no limit)",
        min_account_days="Reject accounts newer than this many days",
        bonus_role="Role that gets extra entries",
        bonus_entries="How many entries the bonus role is worth",
        value="Numeric worth of the prize, needed for Double or Keep (e.g. 5000000)",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="Split or Steal (2 winners)", value="split_steal"),
            app_commands.Choice(name="Double or Nothing", value="double"),
        ]
    )
    async def start(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: app_commands.Range[int, 1, 20] = 1,
        description: str | None = None,
        required_role: discord.Role | None = None,
        channel: discord.TextChannel | None = None,
        mode: app_commands.Choice[str] | None = None,
        claim_hours: app_commands.Range[int, 0, 336] | None = None,
        min_account_days: app_commands.Range[int, 0, 365] = 0,
        bonus_role: discord.Role | None = None,
        bonus_entries: app_commands.Range[int, 1, 10] = 2,
        value: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        mode_value = mode.value if mode else "normal"

        prize_value = parse_value(value) if value else parse_value(prize)
        if mode_value == "double" and prize_value is None:
            await interaction.followup.send(
                embed=error_embed(
                    "Double or Keep needs a prize value to double. Add "
                    "`value:5000000`, or name the prize something like `$5m`."
                )
            )
            return

        # Fall back to the server's configured default when not specified.
        if claim_hours is None:
            settings = await self.bot.db.settings(interaction.guild_id)
            claim_hours = settings.get("default_claim_hours", 24)

        # Split or Steal is a two-player game; anything else makes no sense.
        if mode_value == "split_steal" and winners != 2:
            await interaction.followup.send(
                embed=error_embed(
                    "Split or Steal needs exactly **2** winners — you set "
                    f"{winners}. Set `winners:2` or pick a different mode."
                )
            )
            return
        seconds = parse_duration(duration)
        if seconds is None:
            await interaction.followup.send(
                embed=error_embed(
                    "I couldn't read that duration. Use forms like `30m`, `2h`, "
                    "`3d` or `1d12h`."
                )
            )
            return
        if seconds < 60:
            await interaction.followup.send(
                embed=error_embed("Give it at least a minute.")
            )
            return
        if seconds > 60 * 86400:
            await interaction.followup.send(
                embed=error_embed("Maximum length is 60 days.")
            )
            return

        target = channel or interaction.channel
        perms = target.permissions_for(interaction.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.followup.send(
                embed=error_embed(f"I need Send Messages and Embed Links in {target.mention}.")
            )
            return

        ends_at = time.time() + seconds
        giveaway_id = await self.bot.db.create_giveaway(
            interaction.guild_id,
            target.id,
            prize,
            winners,
            interaction.user.id,
            ends_at,
            description=description,
            required_role=required_role.id if required_role else None,
            mode=mode_value,
            claim_hours=claim_hours,
            min_account_days=min_account_days,
            bonus_role=bonus_role.id if bonus_role else None,
            bonus_entries=bonus_entries,
            value=prize_value,
        )

        giveaway = await self.bot.db.get_giveaway(giveaway_id)
        view = GiveawayView(self, giveaway_id)
        message = await target.send(embed=giveaway_embed(giveaway, 0), view=view)
        await self.bot.db.set_giveaway_message(giveaway_id, message.id)
        self.bot.add_view(GiveawayView(self, giveaway_id), message_id=message.id)

        await interaction.followup.send(
            embed=base_embed(
                "🎉 Giveaway started",
                f"**{prize}** is live in {target.mention}, ending <t:{int(ends_at)}:R>.\n"
                f"Mode: **{MODE_LABELS.get(mode_value, mode_value)}** · "
                f"claim window: {claim_hours}h\n"
                f"Giveaway ID: `{giveaway_id}`",
                accent=YELLOW,
            )
        )

    @group.command(name="end", description="End a running giveaway early")
    @staff_only()
    @app_commands.describe(giveaway_id="ID shown when the giveaway started")
    async def end(self, interaction: discord.Interaction, giveaway_id: int):
        await interaction.response.defer(ephemeral=True)
        giveaway = await self.bot.db.get_giveaway(giveaway_id)

        if not giveaway or giveaway["guild_id"] != interaction.guild_id:
            await interaction.followup.send(embed=error_embed("No giveaway with that ID."))
            return
        if giveaway["ended"]:
            await interaction.followup.send(embed=error_embed("That one already ended."))
            return

        winners = await self.end_giveaway(giveaway)
        await interaction.followup.send(
            embed=base_embed(
                "🎉 Ended",
                f"Drew {len(winners)} winner(s) for **{giveaway['prize']}**.",
                accent=YELLOW,
            )
        )

    @group.command(name="reroll", description="Draw replacement winners")
    @staff_only()
    @app_commands.describe(
        giveaway_id="ID of the finished giveaway", count="How many to redraw"
    )
    async def reroll(
        self,
        interaction: discord.Interaction,
        giveaway_id: int,
        count: app_commands.Range[int, 1, 20] = 1,
    ):
        await interaction.response.defer()
        giveaway = await self.bot.db.get_giveaway(giveaway_id)

        if not giveaway or giveaway["guild_id"] != interaction.guild_id:
            await interaction.followup.send(embed=error_embed("No giveaway with that ID."))
            return
        if not giveaway["ended"]:
            await interaction.followup.send(
                embed=error_embed("That giveaway is still running.")
            )
            return

        # Never redraw someone who already won this giveaway.
        previous = set(await self.bot.db.previous_winners(giveaway_id))
        winners = await self.pick_winners(giveaway, count, exclude=previous)

        if not winners:
            await interaction.followup.send(
                embed=error_embed("No eligible entries left to reroll.")
            )
            return

        await self.bot.db.record_winners(giveaway_id, winners)
        await interaction.followup.send(
            embed=base_embed(
                "🔄 Reroll",
                f"Drew {len(winners)} new winner(s) for **{giveaway['prize']}** — "
                "they'll need to press Claim.",
                accent=YELLOW,
            )
        )
        await self.post_claim(giveaway, winners, rerolled=True)

    @group.command(name="claimtime", description="Change the claim window")
    @staff_only()
    @app_commands.describe(
        giveaway_id="Which giveaway", hours="Hours to claim in (0 = unlimited)"
    )
    async def claimtime(
        self,
        interaction: discord.Interaction,
        giveaway_id: int,
        hours: app_commands.Range[int, 0, 336],
    ):
        giveaway = await self.bot.db.get_giveaway(giveaway_id)
        if not giveaway or giveaway["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(
                embed=error_embed("No giveaway with that ID."), ephemeral=True
            )
            return

        await self.bot.db.update_giveaway(giveaway_id, claim_hours=hours)
        await interaction.response.send_message(
            embed=base_embed(
                "⏱️ Claim window updated",
                f"Winners of **{giveaway['prize']}** now have "
                + (f"**{hours} hour(s)**" if hours else "**unlimited time**")
                + " to press Claim.\n\n*This applies to winners who haven't "
                "expired yet, including ones already drawn.*",
                accent=BLUE,
            )
        )

    @group.command(
        name="claimdefault", description="Set this server's default claim window"
    )
    @staff_only()
    @app_commands.describe(hours="Default hours for new giveaways (0 = unlimited)")
    async def claimdefault(
        self, interaction: discord.Interaction, hours: app_commands.Range[int, 0, 336]
    ):
        await self.bot.db.set_settings(interaction.guild_id, default_claim_hours=hours)
        await interaction.response.send_message(
            embed=base_embed(
                "⏱️ Default claim window set",
                "New giveaways default to "
                + (f"**{hours} hour(s)**." if hours else "**unlimited time**."),
            )
        )

    @group.command(name="edit", description="Change a running giveaway")
    @staff_only()
    @app_commands.describe(
        giveaway_id="Which giveaway",
        prize="New prize name",
        winners="New winner count",
        extend="Add time, e.g. 2h or 1d",
        description="New description",
    )
    async def edit(
        self,
        interaction: discord.Interaction,
        giveaway_id: int,
        prize: str | None = None,
        winners: app_commands.Range[int, 1, 20] | None = None,
        extend: str | None = None,
        description: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        giveaway = await self.bot.db.get_giveaway(giveaway_id)

        if not giveaway or giveaway["guild_id"] != interaction.guild_id:
            await interaction.followup.send(embed=error_embed("No giveaway with that ID."))
            return
        if giveaway["ended"]:
            await interaction.followup.send(
                embed=error_embed("That giveaway has already ended.")
            )
            return

        fields: dict = {}
        if prize:
            fields["prize"] = prize
        if description is not None:
            fields["description"] = description
        if winners:
            if giveaway["mode"] == "split_steal" and winners != 2:
                await interaction.followup.send(
                    embed=error_embed("Split or Steal needs exactly 2 winners.")
                )
                return
            fields["winner_count"] = winners
        if extend:
            seconds = parse_duration(extend)
            if seconds is None:
                await interaction.followup.send(
                    embed=error_embed("Couldn't read that duration — try `2h` or `1d`.")
                )
                return
            fields["ends_at"] = giveaway["ends_at"] + seconds

        if not fields:
            await interaction.followup.send(
                embed=error_embed("Give me at least one thing to change.")
            )
            return

        await self.bot.db.update_giveaway(giveaway_id, **fields)
        updated = await self.bot.db.get_giveaway(giveaway_id)
        await self.refresh_message(updated)

        await interaction.followup.send(
            embed=base_embed(
                "✏️ Giveaway updated",
                f"**{updated['prize']}** now ends <t:{int(updated['ends_at'])}:R> "
                f"with {updated['winner_count']} winner(s).",
            )
        )

    @group.command(name="cancel", description="Cancel a giveaway without drawing")
    @staff_only()
    @app_commands.describe(giveaway_id="Which giveaway")
    async def cancel(self, interaction: discord.Interaction, giveaway_id: int):
        await interaction.response.defer()
        giveaway = await self.bot.db.get_giveaway(giveaway_id)

        if not giveaway or giveaway["guild_id"] != interaction.guild_id:
            await interaction.followup.send(embed=error_embed("No giveaway with that ID."))
            return
        if giveaway["ended"]:
            await interaction.followup.send(embed=error_embed("That one already ended."))
            return

        await self.bot.db.update_giveaway(giveaway_id, ended=1, cancelled=1)

        channel = self.bot.get_channel(giveaway["channel_id"])
        if channel and giveaway["message_id"]:
            try:
                message = await channel.fetch_message(giveaway["message_id"])
                await message.edit(
                    embed=base_embed(
                        f"🚫 Cancelled — {giveaway['prize']}",
                        "This giveaway was cancelled. No winners were drawn.",
                        accent=PINK,
                    ),
                    view=GiveawayView(self, giveaway_id, disabled=True),
                )
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            embed=base_embed(
                "🚫 Cancelled",
                f"**{giveaway['prize']}** cancelled — no winners drawn.",
                accent=PINK,
            )
        )

    @group.command(name="list", description="Show running giveaways")
    async def list_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer()
        active = await self.bot.db.active_giveaways(interaction.guild_id)

        if not active:
            await interaction.followup.send(
                embed=base_embed("🎉 No giveaways running", "Start one with `/giveaway start`.")
            )
            return

        embed = base_embed(f"🎉 Running giveaways — {len(active)}", accent=YELLOW)
        for giveaway in active[:15]:
            count = await self.bot.db.entry_count(giveaway["id"])
            embed.add_field(
                name=f"`{giveaway['id']}` · {giveaway['prize']}",
                value=(
                    f"<#{giveaway['channel_id']}> · ends <t:{int(giveaway['ends_at'])}:R>\n"
                    f"{count} entries · {giveaway['winner_count']} winner(s)"
                ),
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @group.command(name="getdata", description="Browse all giveaway data in tabs")
    @staff_only()
    async def getdata(self, interaction: discord.Interaction):
        await interaction.response.defer()
        view = DataTabs(self, interaction.guild_id, interaction.user.id)
        embed = await view.build()
        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message

    @group.command(name="entries", description="How many people entered a giveaway")
    @app_commands.describe(giveaway_id="ID of the giveaway")
    async def entries(self, interaction: discord.Interaction, giveaway_id: int):
        giveaway = await self.bot.db.get_giveaway(giveaway_id)
        if not giveaway or giveaway["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(
                embed=error_embed("No giveaway with that ID."), ephemeral=True
            )
            return

        count = await self.bot.db.entry_count(giveaway_id)
        embed = base_embed(f"🎉 {giveaway['prize']}", accent=YELLOW)
        embed.add_field(name="Entries", value=str(count), inline=True)
        embed.add_field(
            name="Status",
            value="Ended" if giveaway["ended"] else f"Ends <t:{int(giveaway['ends_at'])}:R>",
            inline=True,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
