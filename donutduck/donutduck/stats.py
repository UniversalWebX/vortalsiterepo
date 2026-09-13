"""One registry for every trackable stat, shared by the tracking, leaderboard
and command-mirror cogs so a new stat only has to be defined once."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .utils import compact, money, playtime, pick, to_number


@dataclass(frozen=True)
class Stat:
    key: str            # our canonical name, used in the DB and command choices
    label: str          # human label for embeds
    emoji: str
    aliases: tuple[str, ...]   # possible field names in the /stats payload
    leaderboard: str | None    # matching /leaderboards/{type} name, if any
    fmt: Callable[[object], str]
    higher_is_better: bool = True

    def extract(self, stats_payload: dict) -> float | None:
        return to_number(pick(stats_payload, *self.aliases))


STATS: dict[str, Stat] = {
    s.key: s
    for s in [
        Stat("money", "Money", "💰", ("money", "balance", "cash"), "money", money),
        Stat("shards", "Shards", "💎", ("shards",), "shards", compact),
        Stat("kills", "Kills", "⚔️", ("kills",), "kills", compact),
        Stat("deaths", "Deaths", "💀", ("deaths",), "deaths", compact, False),
        Stat("playtime", "Playtime", "⏱️", ("playtime", "playtime_ms", "time"), "playtime", playtime),
        Stat("mobskilled", "Mobs killed", "🧟", ("mobs_killed", "mobskilled"), "mobskilled", compact),
        Stat("brokenblocks", "Blocks broken", "⛏️", ("broken_blocks", "brokenblocks"), "brokenblocks", compact),
        Stat("placedblocks", "Blocks placed", "🧱", ("placed_blocks", "placedblocks"), "placedblocks", compact),
        Stat("sell", "Money from /sell", "📈", ("money_made_from_sell", "sell", "moneymade"), "sell", money),
        Stat("shop", "Money spent in /shop", "📉", ("money_spent_on_shop", "shop", "moneyspent"), "shop", money),
    ]
}


def stat_choices():
    """discord.app_commands choices for every stat. Imported lazily by cogs."""
    from discord import app_commands

    return [
        app_commands.Choice(name=f"{s.emoji} {s.label}", value=s.key)
        for s in STATS.values()
    ]


def format_delta(stat: Stat, delta: float) -> str:
    """Signed, formatted change with an arrow that accounts for stats where
    going up is bad (deaths)."""
    if delta == 0:
        return "▬ no change"
    good = delta > 0 if stat.higher_is_better else delta < 0
    arrow = "📈" if delta > 0 else "📉"
    sign = "+" if delta > 0 else "−"
    body = stat.fmt(abs(delta)) if stat.key != "playtime" else playtime(abs(delta))
    marker = "" if good else " ⚠️"
    return f"{arrow} {sign}{body}{marker}"
