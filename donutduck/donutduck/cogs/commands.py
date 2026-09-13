"""Mirrors of in-game DonutSMP commands.

The public API is read-only — there is no endpoint that executes a command on
the server — so anything that *changes* game state (/pay, /sethome, /tpa)
can't be run from Discord by any bot. What this cog does instead:

  * every *informational* in-game command gets a real, working slash command
    that hits the API and returns the same answer (/bal, /shards, /kills, ...)
  * every other command is documented in a lookup (`/donut <command>`) so
    people can still ask the bot what something does.

New mirrors are cheap to add: append to QUICK_STATS or COMMAND_REFERENCE.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..scraper import DonutAPIError
from ..stats import STATS
from ..utils import base_embed, error_embed, head_url, money, pick

# slash command name -> (stat key, in-game equivalent)
QUICK_STATS: dict[str, tuple[str, str]] = {
    "bal": ("money", "/bal"),
    "shards": ("shards", "/shards"),
    "kills": ("kills", "/kills"),
    "deaths": ("deaths", "/deaths"),
    "playtime": ("playtime", "/playtime"),
    "mobskilled": ("mobskilled", "/stats"),
    "blocksbroken": ("brokenblocks", "/stats"),
    "blocksplaced": ("placedblocks", "/stats"),
}

# in-game command -> (what it does, how DonutDuck handles it)
COMMAND_REFERENCE: dict[str, tuple[str, str]] = {
    "/ah": ("Opens the auction house.", "`/ah [item]` — browse listings here."),
    "/ah sell": ("Lists the held item on the AH.", "Must be done in-game."),
    "/ahhistory": (
        "Your auction transaction history.",
        "In-game only — donutstats.org has no sales history page.",
    ),
    "/bal": ("Shows your money.", "`/bal <player>`"),
    "/baltop": ("Richest players.", "`/baltop` or `/leaderboard money`"),
    "/shards": ("Shows your shard count.", "`/shards <player>`"),
    "/stats": ("Your full stat sheet.", "`/stats <player>`"),
    "/findplayer": (
        "Locates an online player.",
        "In-game only — donutstats.org doesn't publish player locations.",
    ),
    "/playtime": ("Total time played.", "`/playtime <player>`"),
    "/pay": ("Sends money to another player.", "In-game only — moves real balances."),
    "/trade": ("Opens a trade with a player.", "In-game only."),
    "/shop": ("Opens the server shop.", "In-game only. `/price` estimates AH values."),
    "/sell": ("Sells the item in your hand.", "In-game only."),
    "/sellall": ("Sells your whole inventory.", "In-game only."),
    "/sethome": ("Sets a home at your position.", "In-game only."),
    "/home": ("Teleports to a home.", "In-game only."),
    "/delhome": ("Deletes a home.", "In-game only."),
    "/tpa": ("Requests a teleport to a player.", "In-game only."),
    "/tpaccept": ("Accepts a teleport request.", "In-game only."),
    "/spawn": ("Returns you to spawn.", "In-game only."),
    "/rtp": ("Random teleport into the wild.", "In-game only."),
    "/kit": ("Claims your available kits.", "In-game only."),
    "/craft": ("Opens a portable crafting table.", "In-game only."),
    "/ec": ("Opens your ender chest.", "In-game only."),
    "/msg": ("Direct-messages a player.", "In-game only."),
    "/ignore": ("Blocks a player's messages.", "In-game only."),
    "/report": ("Reports a rule-breaker.", "In-game only."),
    "/shrine": ("Opens the shrine.", "In-game only."),
    "/vote": ("Vote links for rewards.", "In-game only."),
    "/link": (
        "Links your Minecraft account to your Discord account.",
        "In-game only.",
    ),
    "/api": (
        "Shows your API key, if your account is linked.",
        "Not needed — DonutDuck reads donutstats.org, which needs no key.",
    ),
    "/afk": ("Teleports you to the AFK area.", "In-game only."),
    "/bounty": ("View or place bounties on players.", "In-game only."),
    "/friend": ("Your friends list.", "In-game only."),
    "/block": ("Blocks a player.", "In-game only."),
    "/kill": ("Drops your items and respawns you.", "In-game only."),
    "/leaderboard": (
        "Leaderboards for various stats.",
        "`/leaderboard <board>` here, or `/baltop`.",
    ),
}


def make_stat_command(name: str, stat_key: str, ingame: str):
    """Builds one working slash command per informational in-game command."""
    definition = STATS[stat_key]

    async def callback(interaction: discord.Interaction, player: str):
        await interaction.response.defer()
        try:
            payload = await interaction.client.api.stats(player)
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
                embed=error_embed(f"The API didn't return {definition.label} for `{player}`.")
            )
            return

        embed = base_embed(f"{definition.emoji} {player}", accent=definition.key)
        embed.set_thumbnail(url=head_url(player, 64))
        embed.add_field(name=definition.label, value=definition.fmt(value), inline=False)
        embed.set_footer(text=f"In-game equivalent: {ingame} • DonutDuck")
        await interaction.followup.send(embed=embed)

    command = app_commands.Command(
        name=name,
        description=f"{definition.label} for a player (mirrors {ingame})",
        callback=callback,
    )
    # Give the single parameter a proper description in the Discord UI.
    command._params["player"].description = "Minecraft username"
    return command


class Mirror(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        for name, (stat_key, ingame) in QUICK_STATS.items():
            bot.tree.add_command(make_stat_command(name, stat_key, ingame))

    async def cog_unload(self):
        for name in QUICK_STATS:
            self.bot.tree.remove_command(name)

    @app_commands.command(name="baltop", description="Richest players (mirrors /baltop)")
    @app_commands.describe(page="Page number")
    async def baltop(
        self, interaction: discord.Interaction, page: app_commands.Range[int, 1, 100] = 1
    ):
        await interaction.response.defer()
        try:
            entries = await self.bot.api.leaderboard("money", page)
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if not entries:
            await interaction.followup.send(embed=error_embed("No data on that page."))
            return

        embed = base_embed("💰 Baltop")
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, entry in enumerate(entries[:10]):
            rank = pick(entry, "position", "rank", default=(page - 1) * 10 + i + 1)
            name = pick(entry, "username", "name", "player", default="Unknown")
            value = pick(entry, "value", "amount", "money")
            lines.append(f"{medals.get(int(rank), f'`#{rank}`')} {name} — **{money(value)}**")
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Page {page} • in-game: /baltop • DonutDuck")
        await interaction.followup.send(embed=embed)

    # -------------------------------------------------------------- /donut

    async def command_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = current.lstrip("/").lower()
        matches = [c for c in COMMAND_REFERENCE if query in c.lower()]
        return [app_commands.Choice(name=c, value=c) for c in matches[:25]]

    @app_commands.command(
        name="donut", description="Look up what any DonutSMP command does"
    )
    @app_commands.describe(command="An in-game command, e.g. /sethome")
    @app_commands.autocomplete(command=command_autocomplete)
    async def donut(self, interaction: discord.Interaction, command: str | None = None):
        if command is None:
            embed = base_embed(
                "🍩 DonutSMP commands",
                "Pick one with `/donut <command>` for details. Commands DonutDuck "
                "can run for you are **bold**.",
            )
            runnable = {v[1] for v in QUICK_STATS.values()} | {
                "/ah",
                "/baltop",
                "/stats",
                "/leaderboard",
            }
            names = [
                f"**`{c}`**" if c in runnable else f"`{c}`" for c in COMMAND_REFERENCE
            ]
            embed.add_field(name="All commands", value=" ".join(names), inline=False)
            await interaction.response.send_message(embed=embed)
            return

        key = command if command.startswith("/") else f"/{command}"
        entry = COMMAND_REFERENCE.get(key.lower())

        if entry is None:
            close = [c for c in COMMAND_REFERENCE if key.lstrip("/").lower() in c]
            hint = f"\n\nDid you mean: {', '.join(f'`{c}`' for c in close[:5])}?" if close else ""
            await interaction.response.send_message(
                embed=error_embed(
                    f"I don't have `{key}` in my reference. Try `/donut` with no "
                    f"argument for the full list, or check `/help` in-game.{hint}"
                ),
                ephemeral=True,
            )
            return

        what, how = entry
        embed = base_embed(f"🍩 `{key}`")
        embed.add_field(name="In-game", value=what, inline=False)
        embed.add_field(name="On Discord", value=how, inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Mirror(bot))
