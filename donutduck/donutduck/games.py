"""Outcome rules for the giveaway minigames.

Kept free of Discord objects so the rules can be tested directly — these decide
who actually receives a prize, which is exactly the kind of logic that should
not be buried inside a button callback.
"""

from __future__ import annotations

import random

# Split or steal, the classic Golden Balls endgame.
SPLIT = "split"
STEAL = "steal"

# Double or nothing.
KEEP = "keep"
GAMBLE = "gamble"


def resolve_split_steal(
    prize: str, choice_a: str | None, choice_b: str | None
) -> tuple[str | None, str | None, str]:
    """Return (payout_a, payout_b, summary).

    A payout of None means that player receives nothing.

    Someone who never chose is treated as having split. Defaulting to steal
    would let a player win by simply not participating, and would punish the
    person who did engage.
    """
    a = choice_a or SPLIT
    b = choice_b or SPLIT

    if a == SPLIT and b == SPLIT:
        half = f"half of {prize}"
        return half, half, "Both chose **split** — the prize is shared."

    if a == STEAL and b == SPLIT:
        return prize, None, "One player **stole** and takes the whole prize."

    if a == SPLIT and b == STEAL:
        return None, prize, "One player **stole** and takes the whole prize."

    return None, None, "Both chose **steal** — nobody wins anything."


def resolve_double(prize: str, choice: str, *, odds: float = 0.5, rng=random) -> tuple[str | None, str]:
    """Return (payout, summary). None means the prize is lost and rerolled.

    `odds` is the chance of winning the gamble. It's a parameter rather than a
    hardcoded 0.5 so hosts can tune it and so tests can force an outcome.
    """
    if choice == KEEP:
        return prize, "Kept the prize without gambling."

    if rng.random() < odds:
        return f"double {prize}", "Gambled and **won** — the prize is doubled!"

    return None, "Gambled and **lost** — the prize goes back in the pot for a reroll."


VALUE_RE = __import__("re").compile(
    r"(-?[\d,.]+)\s*([kmbt])?", __import__("re").IGNORECASE
)
_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def parse_value(text: str | None) -> float | None:
    """Pull a number out of a prize string: '$5m' -> 5000000, '1.5b' -> 1.5e9.

    A prize is free text, so 'doubling' it needs a number from somewhere. The
    host can state one explicitly; failing that this reads it from the prize
    name, and if neither works the double option is simply not offered.
    """
    if not text:
        return None
    match = VALUE_RE.search(str(text).replace("$", ""))
    if not match:
        return None
    number, suffix = match.groups()
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        value *= _SUFFIX[suffix.lower()]
    return value if value > 0 else None


def format_value(value: float) -> str:
    """5000000 -> '$5M'. Mirrors how prizes are usually written."""
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= limit:
            trimmed = f"{value / limit:.2f}".rstrip("0").rstrip(".")
            return f"${trimmed}{suffix}"
    return f"${value:,.0f}"


def next_double(
    value: float, cap: float | None, doubles_so_far: int, max_doubles: int = 5
) -> tuple[float | None, str]:
    """Work out the doubled value, or explain why it can't double.

    The cap exists because doubling compounds — five rounds turns $1M into
    $32M, which is how a giveaway bot accidentally promises a fortune.
    """
    if doubles_so_far >= max_doubles:
        return None, f"This prize has already doubled {max_doubles} times."
    doubled = value * 2
    if cap is not None and doubled > cap:
        return None, (
            f"Doubling would reach {format_value(doubled)}, over this server's "
            f"cap of {format_value(cap)}."
        )
    return doubled, f"Doubled to {format_value(doubled)}."


MODE_LABELS = {
    "normal": "Normal",
    "split_steal": "Split or Steal",
    "double": "Double or Keep",
}

MODE_BLURBS = {
    "normal": "Winners claim their prize as usual.",
    "split_steal": (
        "The two winners each secretly choose **split** or **steal**. "
        "Both split → they share it. One steals → that player takes all. "
        "Both steal → nobody gets anything."
    ),
    "double": (
        "The winner may keep the prize and claim it, or double it — which "
        "launches a fresh giveaway worth twice as much, up to the server cap."
    ),
}
