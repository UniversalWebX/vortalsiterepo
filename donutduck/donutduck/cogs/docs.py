"""`/docs` — full documentation, generated from the live command tree.

The listing is built by walking `bot.tree` at runtime rather than from a
hand-written list. A hand-written one goes stale the first time someone adds a
command and forgets to update it; this can't, because it's reading the same
objects Discord was given.

Categories, blurbs and setup notes are the only hand-written parts, since
those describe *why* you'd use something, which no amount of introspection
recovers.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..utils import base_embed, error_embed

# cog name -> (emoji, label, blurb, setup steps)
CATEGORIES: dict[str, tuple[str, str, str, str]] = {
    "Player": (
        "🍩",
        "DonutSMP stats",
        "Player stats, skins and vouch counts, scraped from donutstats.org.",
        "",
    ),
    "Auction": (
        "🏷️",
        "Auction house",
        "Item prices, listing counts and who's selling.",
        "",
    ),
    "Leaderboard": (
        "🏆",
        "Leaderboards",
        "Server-wide rankings for money, kills, playtime and more.",
        "",
    ),
    "Tracking": (
        "📈",
        "Stat tracking",
        "Watch a player's stat and report changes every 12 hours.",
        "`/track money <player>` — that's the whole setup.",
    ),
    "Mirror": (
        "⛏️",
        "In-game command mirrors",
        "Discord versions of DonutSMP's informational commands.",
        "",
    ),
    "Tickets": (
        "🎫",
        "Tickets",
        "Support tickets and applications with panels, transcripts and an index.",
        "1. `/ticketsetup <category> <log channel>`\n"
        "2. `/staffroles add @staff` then `/ticketsync`\n"
        "3. `/tickettype role` for each type\n"
        "4. `/ticketpanel create` then `/ticketpanel post`",
    ),
    "Giveaways": (
        "🎉",
        "Giveaways",
        "Timed giveaways with claim tickets, Split or Steal and Double or Keep.",
        "`/giveaway start prize:$5m duration:2h` — winners press Claim, "
        "which asks for their IGN and opens a ticket.",
    ),
    "Applications": (
        "📋",
        "Applications",
        "Structured application forms with an accept/deny review queue.",
        "`/application setup <review channel> [role]`, then members `/apply`.",
    ),
    "Staff": (
        "🛡️",
        "Staff tools",
        "Staff roles, activity checks, strikes and legit votes.",
        "**Start here:** `/staffroles add @staff` decides who can see tickets "
        "and run giveaways.",
    ),
    "Vouch": (
        "🤝",
        "Vouches",
        "Vouch for someone after a trade or giveaway payout.",
        "`/vouchchannel <channel>` to choose where they post.",
    ),
    "Scripts": (
        "📜",
        "STScript",
        "Write custom commands in a Scratch-like language and run them with `/st`.",
        "`/stscript help` for the language, `/stscript create` to write one.",
    ),
    "Minigames": ("🎲", "Minigames", "Guess the number and higher or lower.", ""),
    "Streams": (
        "🟣",
        "Twitch",
        "Announce when a streamer goes live.",
        "Needs TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in `.env`.",
    ),
    "Server": (
        "👋",
        "Server features",
        "Welcome messages, autorole, self-assign role menus and a starboard.",
        "",
    ),
    "Utility": (
        "🧰",
        "Utilities",
        "Polls, reminders, embeds and info commands.",
        "",
    ),
    "Partner": (
        "🤝",
        "Partnerships",
        "Partner with other servers the bot is in.",
        "Off by default — `/partner setup` enables it.",
    ),
    "Profile": (
        "🖼️",
        "Appearance",
        "Give the bot a different avatar and nickname in this server only.",
        "",
    ),
    "Private": ("🔒", "Private", "Commands limited to one server.", ""),
    "General": ("ℹ️", "General", "Help, status and latency.", ""),
    "Docs": ("📖", "Documentation", "This.", ""),
}

# Module file name -> category key, where they differ.
MODULE_MAP = {
    "commands": "Mirror",
    "scripts": "Scripts",
    "giveaways": "Giveaways",
    "applications": "Applications",
    "minigames": "Minigames",
    "streams": "Streams",
    "tickets": "Tickets",
    "leaderboard": "Leaderboard",
    "tracking": "Tracking",
    "auction": "Auction",
    "player": "Player",
    "staff": "Staff",
    "vouch": "Vouch",
    "server": "Server",
    "utility": "Utility",
    "partner": "Partner",
    "profile": "Profile",
    "private": "Private",
    "general": "General",
    "docs": "Docs",
}

ORDER = [
    "Tickets", "Giveaways", "Applications", "Staff", "Vouch", "Scripts",
    "Player", "Auction", "Leaderboard", "Tracking", "Mirror",
    "Server", "Utility", "Minigames", "Streams", "Partner", "Profile",
    "Private", "General", "Docs",
]


def describe(command, prefix: str = "") -> list[str]:
    """One line per command, including every subcommand of a group."""
    if isinstance(command, app_commands.Group):
        lines = []
        for child in sorted(command.commands, key=lambda c: c.name):
            lines.extend(describe(child, f"{prefix}{command.name} "))
        return lines

    params = " ".join(
        f"<{p.name}>" if p.required else f"[{p.name}]"
        for p in getattr(command, "parameters", [])
    )
    usage = f"`/{prefix}{command.name}{' ' + params if params else ''}`"
    return [f"{usage}\n　↳ {command.description}"]


class Docs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def collect(self, guild: discord.Guild | None) -> dict[str, list[str]]:
        """Group every command by the module it came from.

        Module path rather than `binding`: groups declared as class attributes
        have no binding, which dumped most of the tree into "General".
        """
        grouped: dict[str, list[str]] = {}
        commands_list = list(self.bot.tree.get_commands())
        if guild is not None:
            commands_list += list(self.bot.tree.get_commands(guild=guild))

        for command in commands_list:
            module = getattr(command, "module", "") or ""
            if not module:
                callback = getattr(command, "_callback", None)
                module = getattr(callback, "__module__", "") or ""

            tail = module.rsplit(".", 1)[-1]
            key = MODULE_MAP.get(tail, tail.title())
            if key not in CATEGORIES:
                key = "General"
            grouped.setdefault(key, []).extend(describe(command))

        for lines in grouped.values():
            lines.sort()
        return grouped

    def category_embed(self, key: str, lines: list[str]) -> discord.Embed:
        emoji, label, blurb, setup = CATEGORIES.get(key, ("•", key, "", ""))
        embed = base_embed(f"{emoji} {label}", blurb)

        # Embed fields cap at 1024 chars, so long categories are split.
        chunk, size, part = [], 0, 1
        for line in lines:
            if size + len(line) > 950 and chunk:
                embed.add_field(
                    name=f"Commands ({part})" if part > 1 else "Commands",
                    value="\n".join(chunk),
                    inline=False,
                )
                chunk, size, part = [], 0, part + 1
            chunk.append(line)
            size += len(line) + 1
        if chunk:
            embed.add_field(
                name=f"Commands ({part})" if part > 1 else "Commands",
                value="\n".join(chunk),
                inline=False,
            )

        if setup:
            embed.add_field(name="Setup", value=setup, inline=False)
        embed.set_footer(text=f"{len(lines)} command(s) • /docs for other sections")
        return embed

    @app_commands.command(name="docs", description="Full documentation for every command")
    @app_commands.describe(section="Jump straight to one section")
    async def docs(self, interaction: discord.Interaction, section: str | None = None):
        grouped = self.collect(interaction.guild)

        if section:
            key = next(
                (
                    k
                    for k in grouped
                    if k.lower() == section.lower()
                    or CATEGORIES.get(k, ("", ""))[1].lower() == section.lower()
                ),
                None,
            )
            if key is None:
                await interaction.response.send_message(
                    embed=error_embed(f"No section called `{section}`."), ephemeral=True
                )
                return
            await interaction.response.send_message(
                embed=self.category_embed(key, grouped[key])
            )
            return

        total = sum(len(v) for v in grouped.values())
        overview = base_embed(
            "📖 DonutDuck documentation",
            f"**{total} commands** across {len(grouped)} sections. Pick one below "
            "for usage details.",
        )
        listing = []
        for key in ORDER:
            if key not in grouped:
                continue
            emoji, label, blurb, _ = CATEGORIES[key]
            listing.append(f"{emoji} **{label}** — {len(grouped[key])}\n　{blurb}")
        overview.add_field(name="Sections", value="\n".join(listing)[:1024], inline=False)
        overview.add_field(
            name="First-time setup",
            value=(
                "1. `/staffroles add @staff` — who counts as staff\n"
                "2. `/ticketsetup` then `/ticketpanel create`\n"
                "3. `/application setup` for staff applications\n"
                "4. `/vouchchannel` and `/legitchannel`"
            ),
            inline=False,
        )
        overview.set_footer(text="Also: /help for a short version")

        await interaction.response.send_message(
            embed=overview, view=DocsView(self, grouped)
        )

    @docs.autocomplete("section")
    async def section_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        grouped = self.collect(interaction.guild)
        return [
            app_commands.Choice(name=CATEGORIES[k][1], value=k)
            for k in ORDER
            if k in grouped
            and (not current or current.lower() in CATEGORIES[k][1].lower())
        ][:25]


class DocsView(discord.ui.View):
    """Dropdown of sections. Short-lived, so no persistence needed."""

    def __init__(self, cog: Docs, grouped: dict[str, list[str]]):
        super().__init__(timeout=300)
        self.cog = cog
        self.grouped = grouped

        options = [
            discord.SelectOption(
                label=CATEGORIES[key][1],
                value=key,
                description=CATEGORIES[key][2][:100] or None,
                emoji=CATEGORIES[key][0],
            )
            for key in ORDER
            if key in grouped
        ][:25]
        self.select.options = options or [
            discord.SelectOption(label="No commands", value="none")
        ]

    @discord.ui.select(placeholder="Choose a section…")
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        key = select.values[0]
        if key not in self.grouped:
            await interaction.response.send_message(
                embed=error_embed("That section is empty."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=self.cog.category_embed(key, self.grouped[key]), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Docs(bot))
