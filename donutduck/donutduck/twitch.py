"""Minimal Twitch Helix client for live notifications.

Uses the client-credentials flow: an app access token identifies the bot, not
a user, so nobody has to log in with Twitch. Tokens last ~60 days; this
refreshes on expiry and also retries once on a 401, since a token can be
revoked before its stated expiry.

Credentials come from https://dev.twitch.tv/console/apps — free, and unlike
the DonutSMP key there's no in-game gate. Set TWITCH_CLIENT_ID and
TWITCH_CLIENT_SECRET in .env.
"""

from __future__ import annotations

import asyncio
import logging
import time
import aiohttp

log = logging.getLogger("donutduck.twitch")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix"

# Helix accepts up to 100 user_login params per /streams call, so even a large
# watchlist is one request per poll.
BATCH_SIZE = 100


class TwitchError(Exception):
    pass


class TwitchClient:
    def __init__(self, client_id: str | None, client_secret: str | None):
        self.client_id = client_id
        self.client_secret = client_secret
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_token(self, force: bool = False) -> str:
        if not self.configured:
            raise TwitchError(
                "Twitch isn't configured. Add TWITCH_CLIENT_ID and "
                "TWITCH_CLIENT_SECRET to .env — get them free at "
                "https://dev.twitch.tv/console/apps"
            )

        async with self._lock:
            # 60s of slack so a token can't expire mid-request.
            if not force and self._token and time.monotonic() < self._expires_at - 60:
                return self._token

            await self.start()
            assert self._session is not None
            async with self._session.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
            ) as resp:
                payload = await resp.json(content_type=None)
                if resp.status != 200:
                    message = payload.get("message", "unknown error")
                    raise TwitchError(f"Twitch rejected the credentials: {message}")

            self._token = payload["access_token"]
            self._expires_at = time.monotonic() + float(payload.get("expires_in", 3600))
            log.info("Twitch app token refreshed")
            return self._token

    async def _request(self, path: str, params: list[tuple[str, str]]) -> dict:
        await self.start()
        assert self._session is not None
        token = await self._get_token()

        for attempt in (1, 2):
            headers = {
                "Client-ID": self.client_id or "",
                "Authorization": f"Bearer {token}",
            }
            async with self._session.get(
                f"{HELIX}{path}", params=params, headers=headers
            ) as resp:
                if resp.status == 401 and attempt == 1:
                    # Token revoked early; force a refresh and retry once.
                    token = await self._get_token(force=True)
                    continue
                if resp.status == 429:
                    raise TwitchError("Twitch is rate limiting us; try again shortly.")
                if resp.status != 200:
                    text = await resp.text()
                    raise TwitchError(f"Twitch API error {resp.status}: {text[:200]}")
                return await resp.json(content_type=None)

        raise TwitchError("Twitch authentication failed twice.")

    # ------------------------------------------------------------ endpoints

    async def get_users(self, logins: list[str]) -> dict[str, dict]:
        """Login (lowercased) -> user object. Used to validate a name exists."""
        found: dict[str, dict] = {}
        for i in range(0, len(logins), BATCH_SIZE):
            batch = logins[i : i + BATCH_SIZE]
            data = await self._request("/users", [("login", n) for n in batch])
            for user in data.get("data", []):
                found[user["login"].lower()] = user
        return found

    async def get_streams(self, logins: list[str]) -> dict[str, dict]:
        """Login -> stream object, for those currently live. Anyone absent
        from the result is offline."""
        live: dict[str, dict] = {}
        for i in range(0, len(logins), BATCH_SIZE):
            batch = logins[i : i + BATCH_SIZE]
            data = await self._request("/streams", [("user_login", n) for n in batch])
            for stream in data.get("data", []):
                live[stream["user_login"].lower()] = stream
        return live

    @staticmethod
    def thumbnail(stream: dict, width: int = 1280, height: int = 720) -> str:
        """Helix returns a templated URL with {width}/{height} placeholders.
        A cache-buster is appended so Discord doesn't serve a stale frame."""
        url = (stream.get("thumbnail_url") or "").replace("{width}", str(width)).replace(
            "{height}", str(height)
        )
        return f"{url}?t={int(time.time())}" if url else ""

    @staticmethod
    def profile_image(user: dict | None) -> str | None:
        return (user or {}).get("profile_image_url")
