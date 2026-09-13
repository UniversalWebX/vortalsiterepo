"""Auction house: /ah and /price.

donutstats.org aggregates the auction house **per item** rather than per
listing — it shows an item's cheapest price, how many listings and sellers
exist, and who they are. It does not expose individual listing prices or any
sales history, so the old per-listing browser and `/ahsales` aren't possible
from this source. `/price` reports the cheapest asking price rather than a
median across listings, since only one price per item is published.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..scraper import DonutAPIError
from ..utils import base_embed, error_embed, highlight_embed, money, number

PER_PAGE = 8


class Auction(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ah", description="Browse DonutSMP auction house items")
    @app_commands.describe(item="Filter by item name (blank for popular items)")
    async def ah(self, interaction: discord.Interaction, item: str = ""):
        await interaction.response.defer()
        try:
            items = await self.bot.api.auction_items(item)
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if not items:
            await interaction.followup.send(
                embed=error_embed(
                    f"Nothing listed for `{item}`." if item else "No auction data found."
                )
            )
            return

        embed = base_embed(
            f"🏷️ Auction House — {item}" if item else "🏷️ Auction House · popular items"
        )
        for entry in items[:PER_PAGE]:
            sellers = ", ".join(entry["seller_names"][:5]) or "unknown"
            if len(entry["seller_names"]) > 5:
                sellers += f" +{len(entry['seller_names']) - 5} more"
            embed.add_field(
                name=f"{entry['item']} — {entry['price_display']}",
                value=(
                    f"{entry['listings']} listing(s) · {entry['sellers']} seller(s) · "
                    f"{number(entry['items_listed'])} items\n*{sellers}*"
                ),
                inline=False,
            )
        embed.set_footer(text="Cheapest price per item • data from donutstats.org")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="price", description="Check an item's cheapest price")
    @app_commands.describe(item="Item to price check")
    async def price(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        try:
            entry = await self.bot.api.auction_search(item)
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if not entry:
            await interaction.followup.send(
                embed=error_embed(f"No auction listings found for `{item}`.")
            )
            return

        embed = highlight_embed(f"📊 {entry['item']}")
        embed.add_field(name="Cheapest", value=entry["price_display"], inline=True)
        embed.add_field(name="Listings", value=str(entry["listings"]), inline=True)
        embed.add_field(name="Sellers", value=str(entry["sellers"]), inline=True)
        embed.add_field(
            name="Items on market", value=number(entry["items_listed"]), inline=True
        )

        if entry["price"] and entry["items_listed"]:
            embed.add_field(
                name="Market value",
                value=money(entry["price"] * entry["items_listed"]),
                inline=True,
            )

        if entry["seller_names"]:
            embed.add_field(
                name="Selling", value=", ".join(entry["seller_names"][:10]), inline=False
            )

        embed.set_footer(
            text="Lowest asking price • donutstats.org publishes one price per item"
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Auction(bot))
