"""Formatting helpers shared by the cogs."""

from __future__ import annotations

import re
from typing import Any

import discord

from .theme import BRAND, ERROR, HIGHLIGHT, color_for  # noqa: F401

_NUM_RE = re.compile(r"-?\d[\d,._]*")


def to_number(value: Any) -> float | None:
    """DonutSMP returns money as ints, floats, or strings like '$1,234,567'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUM_RE.search(str(value))
    if not match:
        return None
    cleaned = match.group(0).replace(",", "").replace("_", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def money(value: Any) -> str:
    n = to_number(value)
    if n is None:
        return str(value) if value is not None else "—"
    return f"${n:,.0f}"


def compact(value: Any) -> str:
    """1_250_000 -> 1.25M. Used where embed fields get cramped."""
    n = to_number(value)
    if n is None:
        return str(value) if value is not None else "—"
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= limit:
            return f"{n / limit:.2f}".rstrip("0").rstrip(".") + suffix
    return f"{n:,.0f}"


def number(value: Any) -> str:
    n = to_number(value)
    return f"{n:,.0f}" if n is not None else (str(value) if value is not None else "—")


def playtime(value: Any) -> str:
    """Playtime arrives as a preformatted string, or milliseconds."""
    if isinstance(value, str) and not value.strip().isdigit():
        return value
    n = to_number(value)
    if n is None:
        return "—"
    # Values that large are almost certainly milliseconds.
    seconds = n / 1000 if n > 10_000_000 else n
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def pick(data: dict, *keys: str, default: Any = None) -> Any:
    """Field names vary a little across endpoints; try several."""
    if not isinstance(data, dict):
        return default
    lowered = {str(k).lower().replace("_", ""): v for k, v in data.items()}
    for key in keys:
        norm = key.lower().replace("_", "")
        if norm in lowered and lowered[norm] not in (None, ""):
            return lowered[norm]
    return default


def clean_item_name(raw: Any) -> str:
    """Strip Minecraft colour codes and tidy up namespaced IDs."""
    if raw is None:
        return "Unknown item"
    text = re.sub(r"[§&][0-9a-fk-orA-FK-OR]", "", text_of(raw))
    text = text.replace("minecraft:", "").strip()
    # Raw IDs look like "diamond_pickaxe"; display names are already pretty.
    if text and text == text.lower():
        text = text.replace("_", " ").title()
    return text or "Unknown item"


def text_of(raw: Any) -> str:
    """Item fields are sometimes a dict rather than a plain string."""
    if isinstance(raw, dict):
        for key in ("display_name", "displayName", "name", "id", "type", "item"):
            if raw.get(key):
                return str(raw[key])
        return str(raw)
    return str(raw)


def head_url(username_or_uuid: str, size: int = 128) -> str:
    return f"https://mc-heads.net/avatar/{username_or_uuid}/{size}"


def body_url(username_or_uuid: str) -> str:
    return f"https://mc-heads.net/body/{username_or_uuid}/256"


def error_embed(message: str, title: str = "Something went wrong") -> discord.Embed:
    return discord.Embed(title=f"🍩 {title}", description=message, color=ERROR)


def base_embed(
    title: str, description: str | None = None, *, accent: str | int | None = None
) -> discord.Embed:
    """Blue by default. Pass `accent` a string (a player or stat name) to get a
    stable blue/pink/yellow colour for that subject, or an explicit colour int."""
    if isinstance(accent, int):
        color = accent
    elif isinstance(accent, str):
        color = color_for(accent)
    else:
        color = BRAND
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="DonutDuck • data from the DonutSMP API")
    return embed


def highlight_embed(title: str, description: str | None = None) -> discord.Embed:
    """Yellow — for results worth drawing the eye to."""
    return base_embed(title, description, accent=HIGHLIGHT)


async def resolve_member(guild, user_id: int):
    """Get a Member without relying on the member cache.

    `guild.get_member()` reads only the local cache, which stays empty unless
    the privileged Members intent is enabled. Falling back to `fetch_member`
    (a REST call) means giveaways and tickets work on default intents, at the
    cost of one request per uncached member — so callers should resolve
    lazily rather than resolving a whole entry list up front.

    Returns None if the user has left the guild or can't be fetched.
    """
    import discord

    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden):
        return None
    except discord.HTTPException:
        return None
