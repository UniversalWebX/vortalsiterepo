"""Data backend: scrapes donutstats.org.

The official DonutSMP API needed a key that couldn't be obtained, so this
reads the same figures from donutstats.org, an unofficial community stats
site. No key required.

Design note: pages are parsed from their *rendered text* (label-then-value
regex) rather than from CSS selectors or class names. Class names on a hobby
site change with every restyle, whereas the visible label "Money" next to its
value is the thing the site exists to show and is far less likely to move.
When a field can't be found the parser returns None instead of raising, so one
renamed label degrades a single embed field rather than breaking the command.

No browser automation is used. Every page here is server-rendered PHP at a
plain URL, so an HTTP GET returns the finished HTML — driving a headless
Chromium would add hundreds of MB of memory and seconds of latency per lookup
for identical data.

Values are displayed rounded on the site ("105.76B"), so figures are less
precise than the API's exact integers.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

log = logging.getLogger("donutduck.scraper")

BASE_URL = "https://donutstats.org"

# Sent so the site owner can see who's making requests and contact us.
USER_AGENT = (
    "DonutDuck Discord bot (+https://github.com/) — polite scraper, cached, "
    "low volume"
)

SUFFIXES = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

# Our stat key -> the label shown on the player page
STAT_LABELS = {
    "money": "Money",
    "shards": "Shards",
    "playtime": "Playtime",
    "kills": "Kills",
    "deaths": "Deaths",
    "mobskilled": "Mobs killed",
    "brokenblocks": "Blocks broken",
    "placedblocks": "Blocks placed",
    "sell": "Earned /sell",
    "shop": "Spent /shop",
}

# Our stat key -> the site's ?type= value
LEADERBOARD_TYPES = {
    "money": "money",
    "shards": "shards",
    "kills": "kills",
    "deaths": "deaths",
    "playtime": "playtime",
    "mobskilled": "mobskilled",
    "brokenblocks": "brokenblocks",
    "placedblocks": "placedblocks",
    "sell": "sell",
    "shop": "shop",
}


class DonutAPIError(Exception):
    """Kept under the old name so the cogs' error handling is unchanged."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


DonutStatsError = DonutAPIError  # clearer alias for new code


def parse_site_number(text: Any) -> float | None:
    """'105.76B' -> 1.0576e11. Also handles '$1,234', '1.43T', plain ints.

    The site abbreviates large numbers, so precision is limited to whatever
    it chose to display — 105.76B could be anything in a ~5M range.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)

    cleaned = str(text).strip().replace("$", "").replace(" ", "")
    if not cleaned:
        return None

    # The site sometimes uses a European decimal comma ("17,9T" = 17.9 trillion).
    # A single comma with 1-2 trailing digits is a decimal point, not a
    # thousands separator — treating it as the latter inflates by ~10x.
    if re.match(r"^-?\d{1,3},\d{1,2}\s*[KMBT]?$", cleaned, re.IGNORECASE):
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")

    match = re.match(r"^(-?[\d.]+)\s*([KMBT])?$", cleaned, re.IGNORECASE)
    if not match:
        # Fall back to the first number anywhere in the string.
        loose = re.search(r"-?\d[\d.]*", cleaned)
        if not loose:
            return None
        try:
            return float(loose.group(0))
        except ValueError:
            return None

    number_part, suffix = match.groups()
    try:
        value = float(number_part)
    except ValueError:
        return None
    if suffix:
        value *= SUFFIXES[suffix.upper()]
    return value


class DonutStats:
    """Scrapes donutstats.org. Method names match the old API client so the
    cogs didn't need rewriting."""

    def __init__(
        self,
        api_key: str | None = None,  # accepted and ignored; no key needed now
        *,
        cache_ttl: float = 300.0,
        timeout: float = 20.0,
        min_interval: float = 1.0,
    ):
        # The site refreshes roughly every 30 minutes, so a short cache costs
        # nothing in freshness and spares it a lot of traffic.
        self.cache_ttl = cache_ttl
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[float, Any]] = {}
        self._min_interval = min_interval
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------ fetching

    def _cache_get(self, key: str):
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        self._cache.pop(key, None)
        return None

    def _cache_put(self, key: str, value: Any) -> None:
        if len(self._cache) > 300:
            cutoff = time.monotonic() - self.cache_ttl
            for k, (ts, _) in list(self._cache.items()):
                if ts < cutoff:
                    del self._cache[k]
        self._cache[key] = (time.monotonic(), value)

    async def fetch(self, path: str, params: dict | None = None) -> BeautifulSoup:
        await self.start()
        assert self._session is not None

        cache_key = f"{path}:{sorted((params or {}).items())}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return BeautifulSoup(cached, "lxml")

        # Serialise requests and space them out — this is someone's hobby site.
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

            url = f"{BASE_URL}{path}"
            try:
                async with self._session.get(url, params=params) as resp:
                    if resp.status == 404:
                        raise DonutAPIError("That page doesn't exist on donutstats.org.", 404)
                    if resp.status == 429:
                        raise DonutAPIError(
                            "donutstats.org is rate limiting us. Try again shortly.", 429
                        )
                    if resp.status >= 500:
                        raise DonutAPIError(
                            f"donutstats.org is having problems ({resp.status}).",
                            resp.status,
                        )
                    if resp.status != 200:
                        raise DonutAPIError(f"HTTP {resp.status} from donutstats.org.", resp.status)
                    html = await resp.text()
            except asyncio.TimeoutError:
                raise DonutAPIError("donutstats.org timed out.", 408)
            except aiohttp.ClientError as exc:
                raise DonutAPIError(f"Couldn't reach donutstats.org: {exc}")

        self._cache_put(cache_key, html)
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def page_text(soup: BeautifulSoup) -> str:
        """Visible text with single spaces — what the label regexes run on."""
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    # ------------------------------------------------------------- players

    async def stats(self, username: str) -> dict:
        """Player stats. Shape mimics the old API payload so `Stat.extract`
        and the `pick()` aliases in the cogs keep working."""
        soup = await self.fetch("/player.php", {"user": username})
        text = self.page_text(soup)

        # The search page renders when a player isn't found.
        if re.search(r"(not found|no player|couldn'?t find)", text, re.IGNORECASE):
            return {}

        result: dict[str, Any] = {}
        found_any = False

        for key, label in STAT_LABELS.items():
            # "Money 105.76B" / "Earned /sell 2". The lookahead stops the
            # match at the value so following words aren't swallowed.
            if key == "playtime":
                pattern = rf"{re.escape(label)}\s+([\d.,]+\s*[a-z]*)"
            else:
                pattern = rf"{re.escape(label)}\s+(-?[\d.,]+\s*[KMBT]?)(?=\s|$)"
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            raw = match.group(1).strip()
            found_any = True
            if key == "playtime":
                # The site's playtime formatting is inconsistent, so keep the
                # display string rather than inventing a number from it.
                result["playtime"] = raw
                result["playtime_raw"] = raw
            else:
                value = parse_site_number(raw)
                if value is not None:
                    result[key] = value
                    result[f"{key}_display"] = raw

        if not found_any:
            return {}

        rank = re.search(r"\[([A-Z ]{2,20})\]\s*" + re.escape(username), text)
        if rank:
            result["rank"] = rank.group(1).title()

        vouches = re.search(
            r"(\d+)\s+vouches?\s*\((\d+)\s+normal,\s*(\d+)\s+scam\)", text, re.IGNORECASE
        )
        if vouches:
            result["vouches_total"] = int(vouches.group(1))
            result["vouches_normal"] = int(vouches.group(2))
            result["vouches_scam"] = int(vouches.group(3))

        views = re.search(r"([\d,]+)\s+profile views", text, re.IGNORECASE)
        if views:
            result["profile_views"] = int(views.group(1).replace(",", ""))

        result["_source"] = f"{BASE_URL}/player.php?user={username}"
        return result

    # -------------------------------------------------------- leaderboards

    async def leaderboard(self, board: str, page: int = 1) -> list[dict]:
        """Returns [{position, username, value, value_display}]."""
        site_type = LEADERBOARD_TYPES.get(board, board)
        params: dict[str, Any] = {"type": site_type}
        if page > 1:
            params["page"] = page

        soup = await self.fetch("/leaderboards.php", params)
        rows: list[dict] = []

        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if len(cells) < 3:
                    continue

                rank_text = cells[0].get_text(" ", strip=True)
                if not rank_text.strip("#").strip().isdigit():
                    continue  # header row

                # The player cell holds an avatar image plus the name; the
                # image alt repeats the name, so take the last word.
                name_cell = cells[1]
                for img in name_cell.find_all("img"):
                    img.decompose()
                name = name_cell.get_text(" ", strip=True).split()
                if not name:
                    continue

                value_display = cells[2].get_text(" ", strip=True)
                rows.append(
                    {
                        "position": int(rank_text.strip("#").strip()),
                        "username": name[-1],
                        "value": parse_site_number(value_display),
                        "value_display": value_display,
                    }
                )

        # The site paginates client-side on some boards; slice if we got the
        # whole list back for a page beyond the first.
        if page > 1 and len(rows) > 10:
            start = (page - 1) * 10
            rows = rows[start : start + 10]
        return rows

    # ------------------------------------------------------------ auctions

    async def auction_items(self, search: str = "") -> list[dict]:
        """Auction data on this site is aggregated per item, not per listing:
        each entry is {item, price, price_display, listings, sellers,
        items_listed, seller_names}."""
        params = {"search": search} if search else None
        soup = await self.fetch("/auction-house.php", params)
        text = self.page_text(soup)

        results: list[dict] = []
        # "Gilded Blackstone 1.4M 8 listings, 8 sellers , 71 items listed
        #  Sellers: a, b, c"
        pattern = re.compile(
            r"([A-Za-z][A-Za-z '\-]{2,40}?)\s+"
            r"([\d.,]+\s*[KMBT]?)\s+"
            r"(\d+)\s+listings?,\s*(\d+)\s+sellers?\s*,\s*([\d,]+)\s+items? listed"
            r"(?:\s*Sellers:\s*([a-z0-9_.,\s\u2026\-]{0,400}))?",
            # Deliberately case-sensitive: the lowercase seller-name class is
            # what stops a seller list running into the next item's name.
        )
        for match in pattern.finditer(text):
            item, price, listings, sellers, listed, seller_names = match.groups()
            results.append(
                {
                    "item": item.strip(),
                    "price": parse_site_number(price),
                    "price_display": price.strip(),
                    "listings": int(listings),
                    "sellers": int(sellers),
                    "items_listed": int(listed.replace(",", "")),
                    "seller_names": [
                        s.strip()
                        for s in (seller_names or "").split(",")
                        if s.strip() and s.strip() != "…"
                    ],
                }
            )
        return results

    async def auction_search(self, item: str) -> dict | None:
        """Best match for one item name."""
        items = await self.auction_items(item)
        if not items:
            return None
        target = item.lower().strip()
        for entry in items:
            if entry["item"].lower() == target:
                return entry
        for entry in items:
            if target in entry["item"].lower():
                return entry
        return items[0]

    # -------------------------------------------------------- server stats

    async def server_stats(self) -> dict:
        soup = await self.fetch("/server-stats.php")
        text = self.page_text(soup)
        result: dict[str, Any] = {}

        online = re.search(r"Players online\s*:?\s*([\d,]+)\s*/\s*([\d,]+)", text, re.IGNORECASE)
        if online:
            result["online"] = int(online.group(1).replace(",", ""))
            result["max"] = int(online.group(2).replace(",", ""))

        peak = re.search(r"Peak \(recorded\)\s*:?\s*([\d,]+)", text, re.IGNORECASE)
        if peak:
            result["peak"] = int(peak.group(1).replace(",", ""))

        economy = re.search(r"Total Economy\s*:?\s*([\d.,]+\s*[KMBT]?)", text, re.IGNORECASE)
        if economy:
            result["economy_display"] = economy.group(1).strip()
            result["economy"] = parse_site_number(economy.group(1))

        version = re.search(r"Version\s*:?\s*([^\n]{1,60}?)\s+MOTD", text, re.IGNORECASE)
        if version:
            result["version"] = version.group(1).strip()

        motd = re.search(r"MOTD\s*:?\s*(.{1,120})", text, re.IGNORECASE)
        if motd:
            result["motd"] = motd.group(1).strip()

        return result


