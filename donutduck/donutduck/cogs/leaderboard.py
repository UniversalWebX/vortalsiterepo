"""Leaderboards: /leaderboard, /rank."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..scraper import DonutAPIError
from ..paginator import PageView
from ..utils import base_embed, compact, error_embed, money, pick, playtime

# value -> (label, emoji, formatter)
BOARDS = {
    "money": ("Money", "💰", money),
    "shards": ("Shards", "💎", compact),
    "kills": ("Kills", "⚔️", compact),
    "deaths": ("Deaths", "💀", compact),
    "playtime": ("Playtime", "⏱️", playtime),
    "sell": ("Money from /sell", "📈", money),
    "shop": ("Money spent in /shop", "📉", money),
    "mobskilled": ("Mobs killed", "🧟", compact),
    "brokenblocks": ("Blocks broken", "⛏️", compact),
    "placedblocks": ("Blocks placed", "🧱", compact),
}

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
ENTRIES_PER_PAGE = 10


class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="View a DonutSMP leaderboard")
    @app_commands.describe(board="Which leaderboard", page="Page number")
    @app_commands.choices(
        board=[
            app_commands.Choice(name=f"{emoji} {label}", value=key)
            for key, (label, emoji, _) in BOARDS.items()
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        board: app_commands.Choice[str],
        page: app_commands.Range[int, 1, 100] = 1,
    ):
        await interaction.response.defer()
        key = board.value
        label, emoji, fmt = BOARDS[key]

        async def build(p: int) -> discord.Embed | None:
            entries = await self.bot.api.leaderboard(key, p)
            if not entries:
                return None

            embed = base_embed(f"{emoji} {label} leaderboard", accent=key)
            lines = []
            for i, entry in enumerate(entries[:ENTRIES_PER_PAGE]):
                rank = (p - 1) * ENTRIES_PER_PAGE + i + 1
                if isinstance(entry, dict):
                    name = pick(
                        entry, "username", "name", "player", "user", default="Unknown"
                    )
                    value = pick(entry, "value", "amount", "count", key, "money")
                    rank = pick(entry, "position", "rank", default=rank)
                else:
                    name, value = str(entry), None
                prefix = MEDALS.get(int(rank), f"`#{rank}`")
                suffix = f" — **{fmt(value)}**" if value is not None else ""
                lines.append(f"{prefix} {name}{suffix}")

            embed.description = "\n".join(lines)
            embed.set_footer(text=f"Page {p} • DonutDuck")
            return embed

        try:
            embed = await build(page)
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if embed is None:
            await interaction.followup.send(
                embed=error_embed("No leaderboard data on that page.")
            )
            return

        view = PageView(build, interaction.user.id, page=page)
        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message

    @app_commands.command(
        name="rank", description="Find where a player sits on a leaderboard"
    )
    @app_commands.describe(
        player="Minecraft username",
        board="Which leaderboard",
        depth="How many pages to search (10 players per page)",
    )
    @app_commands.choices(
        board=[
            app_commands.Choice(name=f"{emoji} {label}", value=key)
            for key, (label, emoji, _) in BOARDS.items()
        ]
    )
    async def rank(
        self,
        interaction: discord.Interaction,
        player: str,
        board: app_commands.Choice[str],
        depth: app_commands.Range[int, 1, 20] = 10,
    ):
        await interaction.response.defer()
        key = board.value
        label, emoji, fmt = BOARDS[key]
        target = player.lower()

        try:
            for p in range(1, depth + 1):
                entries = await self.bot.api.leaderboard(key, p)
                if not entries:
                    break
                for i, entry in enumerate(entries):
                    name = (
                        pick(entry, "username", "name", "player", "user", default="")
                        if isinstance(entry, dict)
                        else str(entry)
                    )
                    if str(name).lower() != target:
                        continue
                    rank = (
                        pick(entry, "position", "rank", default=(p - 1) * 10 + i + 1)
                        if isinstance(entry, dict)
                        else (p - 1) * 10 + i + 1
                    )
                    value = (
                        pick(entry, "value", "amount", "count", key)
                        if isinstance(entry, dict)
                        else None
                    )
                    embed = base_embed(f"{emoji} {name} — {label}", accent=key)
                    embed.add_field(name="Rank", value=f"#{rank}", inline=True)
                    if value is not None:
                        embed.add_field(name=label, value=fmt(value), inline=True)
                    await interaction.followup.send(embed=embed)
                    return
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        await interaction.followup.send(
            embed=error_embed(
                f"`{player}` isn't in the top {depth * 10} for **{label}**. "
                "Try a larger `depth`."
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
