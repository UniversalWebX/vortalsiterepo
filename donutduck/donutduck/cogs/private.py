"""Commands locked to a single Discord server.

Everything here is registered with `@app_commands.guilds(PRIVATE_GUILD_ID)`,
so Discord itself only ever exposes these commands inside that one server —
they aren't hidden globals, they're never uploaded anywhere else, and no
other server can invoke them even if someone knows the names.

A background poller snapshots the three tracked balances every 3 hours so
`/balhis` has a dense enough series to draw a chart from. It writes to the
same `snapshots` table `/track` uses, so `/history money <player>` works on
this data too.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..scraper import DonutAPIError
from ..chart import render_balance_chart
from ..stats import STATS
from ..theme import BLUE, PINK, YELLOW
from ..utils import base_embed, error_embed, head_url, money

log = logging.getLogger("donutduck.private")

PRIVATE_GUILD_ID = 1504931329156976721
GUILD = discord.Object(id=PRIVATE_GUILD_ID)

# slash command name -> (minecraft username, embed colour)
# The published copy uses placeholder players; put the real usernames (and
# matching command names) here in your own copy.
TRACKED = {
    "player1bal": ("PlayerOne", BLUE),
    "player2bal": ("PlayerTwo", PINK),
    "player3bal": ("PlayerThree", YELLOW),
}

POLL_HOURS = 3
MONEY = STATS["money"]


class Private(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.balance_poller.start()

    async def cog_unload(self):
        self.balance_poller.cancel()

    # ---------------------------------------------------------- background

    @tasks.loop(hours=POLL_HOURS)
    async def balance_poller(self):
        """Snapshot the three balances so /balhis always has a series."""
        if self.bot.get_guild(PRIVATE_GUILD_ID) is None:
            return  # bot isn't in that server; nothing to collect for

        for player, _ in TRACKED.values():
            try:
                payload = await self.bot.api.stats(player)
            except DonutAPIError as exc:
                log.warning("Balance poll failed for %s: %s", player, exc)
                continue

            value = MONEY.extract(payload or {})
            if value is not None:
                await self.bot.db.add_snapshot(player, "money", value)
            await asyncio.sleep(0.5)

        log.info("Balance snapshots recorded")

    @balance_poller.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------ balances

    async def _balance_embed(self, player: str, color: int) -> discord.Embed:
        payload = await self.bot.api.stats(player)
        if not payload:
            return error_embed(f"No stats found for `{player}`.")

        value = MONEY.extract(payload)
        if value is None:
            return error_embed(f"The API didn't return a balance for `{player}`.")

        # Store every manual check too — free data points for the chart.
        await self.bot.db.add_snapshot(player, "money", value)

        embed = base_embed(f"💰 {player}", accent=color)
        embed.set_thumbnail(url=head_url(player, 64))
        embed.add_field(name="Balance", value=money(value), inline=False)

        history = await self.bot.db.history(player, "money", limit=60)
        if len(history) > 1:
            day_ago = time.time() - 86400
            older = [row for row in history if row["taken_at"] <= day_ago]
            reference = older[0] if older else history[-1]
            delta = value - reference["value"]
            window = (time.time() - reference["taken_at"]) / 3600
            arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "▬")
            sign = "+" if delta > 0 else ("−" if delta < 0 else "")
            embed.add_field(
                name=f"Last {window:.0f}h",
                value=f"{arrow} {sign}{money(abs(delta))}",
                inline=True,
            )
            embed.add_field(name="Data points", value=str(len(history)), inline=True)

        embed.set_footer(text="DonutDuck • /balhis for the chart")
        return embed

    @app_commands.command(name="player1bal", description="Balance of PlayerOne")
    @app_commands.guilds(GUILD)
    async def player1bal(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player, color = TRACKED["player1bal"]
        try:
            embed = await self._balance_embed(player, color)
        except DonutAPIError as exc:
            embed = error_embed(str(exc))
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="player2bal", description="Balance of PlayerTwo")
    @app_commands.guilds(GUILD)
    async def player2bal(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player, color = TRACKED["player2bal"]
        try:
            embed = await self._balance_embed(player, color)
        except DonutAPIError as exc:
            embed = error_embed(str(exc))
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="player3bal", description="Balance of PlayerThree")
    @app_commands.guilds(GUILD)
    async def player3bal(self, interaction: discord.Interaction):
        await interaction.response.defer()
        player, color = TRACKED["player3bal"]
        try:
            embed = await self._balance_embed(player, color)
        except DonutAPIError as exc:
            embed = error_embed(str(exc))
        await interaction.followup.send(embed=embed)

    # -------------------------------------------------------------- chart

    @app_commands.command(
        name="balhis", description="Balance history chart for the tracked players"
    )
    @app_commands.describe(
        player="Chart one player only (defaults to all three)",
        days="How far back to plot",
    )
    @app_commands.choices(
        player=[
            app_commands.Choice(name="PlayerOne", value="PlayerOne"),
            app_commands.Choice(name="PlayerTwo", value="PlayerTwo"),
            app_commands.Choice(name="PlayerThree", value="PlayerThree"),
            app_commands.Choice(name="All three", value="__all__"),
        ]
    )
    @app_commands.guilds(GUILD)
    async def balhis(
        self,
        interaction: discord.Interaction,
        player: app_commands.Choice[str] | None = None,
        days: app_commands.Range[int, 1, 90] = 7,
    ):
        await interaction.response.defer()

        selection = player.value if player else "__all__"
        players = (
            [name for name, _ in TRACKED.values()]
            if selection == "__all__"
            else [selection]
        )

        cutoff = time.time() - days * 86400
        series: dict[str, list[tuple[float, float]]] = {}
        for name in players:
            rows = await self.bot.db.history(name, "money", limit=500)
            points = [
                (row["taken_at"], row["value"])
                for row in reversed(rows)  # oldest first
                if row["taken_at"] >= cutoff
            ]
            if points:
                series[name] = points

        if not any(len(points) >= 2 for points in series.values()):
            embed = error_embed(
                f"Not enough history yet to draw a chart for the last {days} day(s).\n\n"
                f"Balances are sampled every {POLL_HOURS} hours, and every "
                "`/player1bal`, `/player2bal` or `/player3bal` check adds a point too — "
                "run those a few times or give it a day.",
                title="Still collecting data",
            )
            await interaction.followup.send(embed=embed)
            return

        title = (
            f"Balance history · last {days} day{'s' if days != 1 else ''}"
            if selection == "__all__"
            else f"{selection} · last {days} day{'s' if days != 1 else ''}"
        )

        try:
            png = await render_balance_chart(series, title)
        except Exception:
            log.exception("Chart render failed")
            await interaction.followup.send(
                embed=error_embed("Couldn't render the chart.")
            )
            return

        file = discord.File(io.BytesIO(png), filename="balhis.png")
        embed = base_embed("📊 Balance history")
        embed.set_image(url="attachment://balhis.png")

        for name, points in series.items():
            first, last = points[0][1], points[-1][1]
            change = last - first
            pct = (change / first * 100) if first else 0
            arrow = "📈" if change > 0 else ("📉" if change < 0 else "▬")
            sign = "+" if change > 0 else ("−" if change < 0 else "")
            embed.add_field(
                name=name,
                value=(
                    f"**{money(last)}**\n{arrow} {sign}{money(abs(change))} "
                    f"({sign}{abs(pct):.1f}%)"
                ),
                inline=True,
            )

        embed.set_footer(
            text=f"Sampled every {POLL_HOURS}h • {sum(len(p) for p in series.values())} points"
        )
        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(Private(bot))
