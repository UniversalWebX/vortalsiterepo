"""Player-facing commands: /stats, /lookup, /skin, /networth."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..scraper import DonutAPIError
from ..utils import (
    base_embed,
    body_url,
    compact,
    error_embed,
    money,
    number,
    pick,
    playtime,
    to_number,
)


class Player(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Show a player's DonutSMP stats")
    @app_commands.describe(player="Minecraft username or UUID")
    async def stats(self, interaction: discord.Interaction, player: str):
        await interaction.response.defer()
        try:
            data = await self.bot.api.stats(player)
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if not data:
            await interaction.followup.send(
                embed=error_embed(f"No stats found for `{player}`.")
            )
            return

        embed = base_embed(f"🍩 Stats — {player}", accent=player)
        embed.set_thumbnail(url=body_url(player))
        embed.url = f"https://donutstats.org/player.php?user={player}"

        balance = pick(data, "money", "balance", "cash")
        shards = pick(data, "shards")
        kills = pick(data, "kills")
        deaths = pick(data, "deaths")

        embed.add_field(name="💰 Balance", value=money(balance), inline=True)
        embed.add_field(name="💎 Shards", value=number(shards), inline=True)
        embed.add_field(
            name="⏱️ Playtime",
            value=playtime(pick(data, "playtime", "playtime_ms", "time")),
            inline=True,
        )

        k, d = to_number(kills), to_number(deaths)
        kdr = f"{k / d:.2f}" if k is not None and d else ("∞" if k else "—")
        embed.add_field(name="⚔️ Kills", value=number(kills), inline=True)
        embed.add_field(name="💀 Deaths", value=number(deaths), inline=True)
        embed.add_field(name="📊 K/D", value=kdr, inline=True)

        embed.add_field(
            name="🧟 Mobs killed",
            value=compact(pick(data, "mobs_killed", "mobskilled")),
            inline=True,
        )
        embed.add_field(
            name="⛏️ Blocks broken",
            value=compact(pick(data, "broken_blocks", "brokenblocks")),
            inline=True,
        )
        embed.add_field(
            name="🧱 Blocks placed",
            value=compact(pick(data, "placed_blocks", "placedblocks")),
            inline=True,
        )

        vouch_total = pick(data, "vouches_total")
        if vouch_total is not None:
            embed.add_field(
                name="🤝 Vouches",
                value=(
                    f"{number(vouch_total)} total\n"
                    f"{number(pick(data, 'vouches_normal', default=0))} normal · "
                    f"{number(pick(data, 'vouches_scam', default=0))} scam"
                ),
                inline=True,
            )

        sold = pick(data, "money_made_from_sell", "sell", "moneymade")
        spent = pick(data, "money_spent_on_shop", "shop", "moneyspent")
        if sold is not None or spent is not None:
            embed.add_field(name="📈 Earned via /sell", value=money(sold), inline=True)
            embed.add_field(name="📉 Spent in /shop", value=money(spent), inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="skin", description="Render a player's Minecraft skin")
    @app_commands.describe(player="Minecraft username or UUID")
    async def skin(self, interaction: discord.Interaction, player: str):
        embed = base_embed(f"🧍 Skin — {player}", accent=player)
        embed.set_image(url=body_url(player))
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Player(bot))
