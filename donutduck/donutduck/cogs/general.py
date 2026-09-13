"""General/utility commands: /help, /ping, /status, /economy."""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from ..scraper import DonutAPIError
from ..utils import base_embed, compact, error_embed, money, pick, to_number


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="What DonutDuck can do")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = base_embed(
            "🍩🦆 DonutDuck",
            "A multi-purpose DonutSMP bot, powered by donutstats.org.",
        )
        embed.add_field(
            name="Players",
            value=(
                "`/stats <player>` — full stat sheet and vouches\n"
                "`/skin <player>` — render their skin"
            ),
            inline=False,
        )
        embed.add_field(
            name="Auction house",
            value=(
                "`/ah [item] [sort]` — browse listings\n"
                
                "`/price <item>` — cheapest / median / average"
            ),
            inline=False,
        )
        embed.add_field(
            name="Leaderboards",
            value=(
                "`/leaderboard <board>` — top players\n"
                "`/rank <player> <board>` — find someone's position\n"
                "`/baltop` — richest players"
            ),
            inline=False,
        )
        embed.add_field(
            name="Tracking",
            value=(
                "`/track <stat> <player>` — report changes every 12h\n"
                "`/untrack <stat> <player>` — stop tracking\n"
                "`/trackers` — what this server is watching\n"
                "`/history <stat> <player>` — recorded snapshots"
            ),
            inline=False,
        )
        embed.add_field(
            name="In-game command mirrors",
            value=(
                "`/bal` `/shards` `/kills` `/deaths` `/playtime` "
                "`/blocksbroken` `/blocksplaced`\n"
                "`/donut <command>` — what any DonutSMP command does"
            ),
            inline=False,
        )
        embed.add_field(
            name="Partners *(Manage Server)*",
            value=(
                "`/partner setup` — enable and configure your listing\n"
                "`/partner browse` — servers open to partnering\n"
                "`/partner request` · `/partner list` · `/partner toggle`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Giveaways *(Manage Server)*",
            value=(
                "`/giveaway start <prize> <duration>` — e.g. `2h`, `3d`, `1d12h`\n"
                "`/giveaway end` · `/giveaway reroll` · `/giveaway list`\n"
                "Winners get a claim ticket opened automatically."
            ),
            inline=False,
        )
        embed.add_field(
            name="Tickets",
            value=(
                "`/ticketsetup` — configure and seed default types\n"
                "`/ticketpanel create|post|edit|refresh|delete` — panels\n"
                "`/tickettype add|remove|role|questions|toggle|list`\n"
                "In a ticket: `/close` `/ticketadd` `/ticketremove` `/tickets`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Applications",
            value=(
                "`/apply <form>` — fill in an application\n"
                "`/application setup` — create the staff form *(Manage Server)*\n"
                "`/application create` · `questions` · `toggle` · `list`\n"
                "`/applications` — pending queue"
            ),
            inline=False,
        )
        embed.add_field(
            name="Twitch *(Manage Server)*",
            value=(
                "`/twitch add <streamer> <channel>` — live notifications\n"
                "`/twitch remove` · `/twitch list` · `/twitch test`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Vouches",
            value=(
                "`/vouch <user> [message]` — vouch for someone\n"
                "`/vouches` · `/vouchtop` · `/vouchchannel`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Server features",
            value=(
                "`/welcome set` · `goodbye` · `autorole` — greetings and auto roles\n"
                "`/rolemenu` — self-assign roles from a dropdown\n"
                "`/starboard` — repost popular messages"
            ),
            inline=False,
        )
        embed.add_field(
            name="Utilities",
            value=(
                "`/poll` — native Discord poll\n"
                "`/remind` · `/reminders` — reminders\n"
                "`/embed` · `/serverinfo` · `/userinfo`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Appearance *(Manage Server)*",
            value=(
                "`/serverprofile avatar` — a custom face for this server only\n"
                "`/serverprofile nickname` · `/serverprofile view` · `reset`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Server",
            value="`/status` — player count & version\n`/ping` — bot latency",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="Check bot and API latency")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.defer()
        gateway = round(self.bot.latency * 1000)

        start = time.perf_counter()
        api_state = "✅ reachable"
        try:
            await self.bot.api.leaderboard("money", 1)
        except DonutAPIError as exc:
            api_state = f"⚠️ {exc}"
        api_ms = round((time.perf_counter() - start) * 1000)

        embed = base_embed("🏓 Pong")
        embed.add_field(name="Gateway", value=f"{gateway} ms", inline=True)
        embed.add_field(name="donutstats.org", value=f"{api_ms} ms", inline=True)
        embed.add_field(name="Source status", value=api_state, inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="status", description="DonutSMP server status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await self.bot.api.server_stats()
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if not data:
            await interaction.followup.send(
                embed=error_embed("Couldn't read the server stats page.")
            )
            return

        embed = base_embed("🍩 DonutSMP")
        if "online" in data:
            embed.add_field(
                name="Players online",
                value=f"{data['online']:,} / {data.get('max', 0):,}",
                inline=True,
            )
        if "peak" in data:
            embed.add_field(name="Peak recorded", value=f"{data['peak']:,}", inline=True)
        if data.get("economy_display"):
            embed.add_field(
                name="Total economy", value=data["economy_display"], inline=True
            )
        if data.get("version"):
            embed.add_field(name="Version", value=data["version"], inline=True)
        if data.get("motd"):
            embed.add_field(name="MOTD", value=data["motd"][:1024], inline=False)

        embed.add_field(name="Java", value="`java.donutsmp.net`", inline=True)
        embed.add_field(name="Bedrock", value="`bedrock.donutsmp.net`", inline=True)
        embed.set_footer(text="Data from donutstats.org • DonutDuck")
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="economy", description="Total money held by the top players"
    )
    @app_commands.describe(pages="Leaderboard pages to sum (10 players each)")
    async def economy(
        self, interaction: discord.Interaction, pages: app_commands.Range[int, 1, 20] = 10
    ):
        await interaction.response.defer()
        total = 0.0
        counted = 0
        try:
            for p in range(1, pages + 1):
                entries = await self.bot.api.leaderboard("money", p)
                if not entries:
                    break
                for entry in entries:
                    value = to_number(
                        pick(entry, "value", "amount", "money")
                        if isinstance(entry, dict)
                        else None
                    )
                    if value is not None:
                        total += value
                        counted += 1
        except DonutAPIError as exc:
            await interaction.followup.send(embed=error_embed(str(exc)))
            return

        if not counted:
            await interaction.followup.send(
                embed=error_embed("Couldn't read money values from the leaderboard.")
            )
            return

        embed = base_embed("💰 Top-player economy")
        embed.add_field(name="Combined balance", value=money(total), inline=True)
        embed.add_field(name="Short", value=compact(total), inline=True)
        embed.add_field(name="Players counted", value=f"{counted:,}", inline=True)
        embed.add_field(name="Average", value=money(total / counted), inline=True)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
