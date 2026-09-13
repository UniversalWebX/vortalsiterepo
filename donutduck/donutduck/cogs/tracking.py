"""Stat tracking: /track, /untrack, /trackers, /history.

A single background loop wakes every 30 minutes and processes any tracker
whose last run was more than 12 hours ago. Staggering it this way means a
restart doesn't reset everyone's schedule, and adding a tracker at 3pm
reports at 3am rather than whenever the bot happened to boot.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..scraper import DonutAPIError
from ..stats import STATS, format_delta, stat_choices
from ..utils import base_embed, error_embed, head_url

log = logging.getLogger("donutduck.tracking")

INTERVAL_HOURS = 12
INTERVAL_SECONDS = INTERVAL_HOURS * 3600
CHECK_EVERY_MINUTES = 30
MAX_TRACKERS_PER_GUILD = 25


class Tracking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tracker_loop.start()

    async def cog_unload(self):
        self.tracker_loop.cancel()

    # --------------------------------------------------------------- loop

    @tasks.loop(minutes=CHECK_EVERY_MINUTES)
    async def tracker_loop(self):
        try:
            due = await self.bot.db.due_trackers(INTERVAL_SECONDS)
        except Exception:
            log.exception("Couldn't read due trackers")
            return

        if not due:
            return
        log.info("Running %d due tracker(s)", len(due))

        # Cache per player so tracking 5 stats for one player is 1 API call.
        stats_cache: dict[str, dict] = {}

        for tracker in due:
            try:
                await self._run_tracker(tracker, stats_cache)
            except Exception:
                log.exception("Tracker %s failed", tracker["id"])
            await asyncio.sleep(0.5)  # be gentle with the API

        await self.bot.db.prune_snapshots()

    async def _run_tracker(self, tracker, stats_cache: dict[str, dict]) -> None:
        player = tracker["player"]
        stat = STATS.get(tracker["stat"])
        if stat is None:
            await self.bot.db.delete_tracker_by_id(tracker["id"])
            return

        key = player.lower()
        if key not in stats_cache:
            try:
                stats_cache[key] = await self.bot.api.stats(player) or {}
            except DonutAPIError as exc:
                log.warning("Stats fetch failed for %s: %s", player, exc)
                # Push the retry out by a cycle rather than dropping the tracker.
                await self.bot.db.mark_run(tracker["id"], tracker["last_value"])
                return

        payload = stats_cache[key]
        value = stat.extract(payload)
        previous = tracker["last_value"]

        if value is None:
            await self.bot.db.mark_run(tracker["id"], previous)
            return

        await self.bot.db.add_snapshot(player, stat.key, value)
        await self.bot.db.mark_run(tracker["id"], value)

        # First run establishes the baseline; nothing to report yet.
        if previous is None:
            return

        channel = self.bot.get_channel(tracker["channel_id"])
        if channel is None:
            return

        delta = value - previous
        embed = base_embed(f"{stat.emoji} {player} — {stat.label}", accent=stat.key)
        embed.set_thumbnail(url=head_url(player, 64))
        embed.add_field(name="Now", value=stat.fmt(value), inline=True)
        embed.add_field(name=f"{INTERVAL_HOURS}h ago", value=stat.fmt(previous), inline=True)
        embed.add_field(name="Change", value=format_delta(stat, delta), inline=True)
        embed.set_footer(text=f"Tracked every {INTERVAL_HOURS}h • /untrack to stop")

        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.warning("Couldn't post tracker %s to channel", tracker["id"])

    @tracker_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    # ----------------------------------------------------------- commands

    @app_commands.command(
        name="track", description="Track a player's stat and report changes every 12 hours"
    )
    @app_commands.describe(
        stat="Which stat to watch",
        player="Minecraft username",
        channel="Where to post updates (defaults to this channel)",
    )
    @app_commands.choices(stat=stat_choices())
    @app_commands.guild_only()
    async def track(
        self,
        interaction: discord.Interaction,
        stat: app_commands.Choice[str],
        player: str,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer()
        target = channel or interaction.channel
        definition = STATS[stat.value]

        perms = target.permissions_for(interaction.guild.me)
        if not (perms.send_messages and perms.embed_links):
            await interaction.followup.send(
                embed=error_embed(
                    f"I can't post in {target.mention} — I need Send Messages and Embed Links there."
                )
            )
            return

        existing = await self.bot.db.guild_trackers(interaction.guild_id)
        if len(existing) >= MAX_TRACKERS_PER_GUILD:
            await interaction.followup.send(
                embed=error_embed(
                    f"This server is at the limit of {MAX_TRACKERS_PER_GUILD} trackers. "
                    "Remove one with `/untrack` first."
                )
            )
            return

        # Verify the player exists and grab a baseline immediately, so the
        # first report 12h from now already has something to compare against.
        try:
            payload = await self.bot.api.stats(player)
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if not payload:
            await interaction.followup.send(
                embed=error_embed(f"No stats found for `{player}`.")
            )
            return

        value = definition.extract(payload)
        if value is None:
            await interaction.followup.send(
                embed=error_embed(
                    f"The API didn't return **{definition.label}** for `{player}`."
                )
            )
            return

        added = await self.bot.db.add_tracker(
            interaction.guild_id, target.id, interaction.user.id, player, definition.key
        )
        if not added:
            await interaction.followup.send(
                embed=error_embed(
                    f"**{definition.label}** is already tracked for `{player}` here."
                )
            )
            return

        # Seed the baseline.
        trackers = await self.bot.db.guild_trackers(interaction.guild_id)
        for row in trackers:
            if row["player"] == player and row["stat"] == definition.key:
                await self.bot.db.mark_run(row["id"], value)
                break
        await self.bot.db.add_snapshot(player, definition.key, value)

        embed = base_embed(f"{definition.emoji} Now tracking {player}", accent=definition.key)
        embed.set_thumbnail(url=head_url(player, 64))
        embed.add_field(name="Stat", value=definition.label, inline=True)
        embed.add_field(name="Baseline", value=definition.fmt(value), inline=True)
        embed.add_field(name="Updates in", value=f"{INTERVAL_HOURS} hours", inline=True)
        embed.add_field(name="Posting to", value=target.mention, inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="untrack", description="Stop tracking a stat for a player")
    @app_commands.describe(stat="Which stat", player="Minecraft username")
    @app_commands.choices(stat=stat_choices())
    @app_commands.guild_only()
    async def untrack(
        self,
        interaction: discord.Interaction,
        stat: app_commands.Choice[str],
        player: str,
    ):
        removed = await self.bot.db.remove_tracker(
            interaction.guild_id, player, stat.value
        )
        definition = STATS[stat.value]
        if removed:
            await interaction.response.send_message(
                embed=base_embed(
                    "🛑 Tracker removed",
                    f"No longer tracking **{definition.label}** for `{player}`.",
                )
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(
                    f"**{definition.label}** wasn't being tracked for `{player}`."
                ),
                ephemeral=True,
            )

    @app_commands.command(name="trackers", description="List this server's active trackers")
    @app_commands.guild_only()
    async def trackers(self, interaction: discord.Interaction):
        rows = await self.bot.db.guild_trackers(interaction.guild_id)
        if not rows:
            await interaction.response.send_message(
                embed=base_embed(
                    "📋 No trackers yet",
                    "Start one with `/track <stat> <player>`.",
                )
            )
            return

        embed = base_embed(f"📋 Trackers — {len(rows)}/{MAX_TRACKERS_PER_GUILD}")
        lines = []
        for row in rows:
            definition = STATS.get(row["stat"])
            if definition is None:
                continue
            current = (
                definition.fmt(row["last_value"]) if row["last_value"] is not None else "—"
            )
            next_run = row["last_run"] + INTERVAL_SECONDS
            when = f"<t:{int(next_run)}:R>" if row["last_run"] else "soon"
            lines.append(
                f"{definition.emoji} **{row['player']}** · {definition.label} — "
                f"`{current}` · next {when} · <#{row['channel_id']}>"
            )
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="history", description="Show recorded snapshots for a tracked stat"
    )
    @app_commands.describe(stat="Which stat", player="Minecraft username")
    @app_commands.choices(stat=stat_choices())
    async def history(
        self,
        interaction: discord.Interaction,
        stat: app_commands.Choice[str],
        player: str,
    ):
        await interaction.response.defer()
        definition = STATS[stat.value]
        rows = await self.bot.db.history(player, definition.key, limit=15)

        if not rows:
            await interaction.followup.send(
                embed=error_embed(
                    f"No history for `{player}` yet. Start one with "
                    f"`/track {definition.key} {player}`."
                )
            )
            return

        embed = base_embed(f"{definition.emoji} {player} — {definition.label} history", accent=definition.key)
        embed.set_thumbnail(url=head_url(player, 64))

        lines = []
        ordered = list(rows)  # newest first
        for i, row in enumerate(ordered):
            change = ""
            if i + 1 < len(ordered):
                delta = row["value"] - ordered[i + 1]["value"]
                change = f" · {format_delta(definition, delta)}"
            lines.append(
                f"<t:{int(row['taken_at'])}:f> — **{definition.fmt(row['value'])}**{change}"
            )
        embed.description = "\n".join(lines)

        oldest, newest = ordered[-1], ordered[0]
        span_hours = max(1, (newest["taken_at"] - oldest["taken_at"]) / 3600)
        total = newest["value"] - oldest["value"]
        embed.add_field(
            name=f"Over {span_hours:.0f}h",
            value=format_delta(definition, total),
            inline=True,
        )
        embed.add_field(
            name="Per day",
            value=definition.fmt(total / (span_hours / 24)) if span_hours >= 1 else "—",
            inline=True,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tracking(bot))
