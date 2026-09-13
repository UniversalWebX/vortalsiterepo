"""Keeps a freedns.afraid.org hostname pointed at this machine.

FreeDNS gives you a **hostname**, not a server — you still host the dashboard
yourself. What this does is the dynamic-DNS half: home and most VPS
connections change IP, and FreeDNS drops a record that isn't refreshed, so
something has to ping their update URL periodically.

Get the URL from https://freedns.afraid.org/dynamic/ — click "Direct URL" for
your subdomain. It looks like:

    https://sync.afraid.org/u/AbCdEf123456/

Put it in FREEDNS_UPDATE_URL. The token in that URL is a credential, so it
belongs in .env, never in code or a repo.
"""

from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("donutduck.ddns")

CHECK_IP_URL = "https://api.ipify.org"


class FreeDNSUpdater:
    def __init__(self, update_url: str | None):
        self.update_url = update_url
        self._last_ip: str | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def configured(self) -> bool:
        return bool(self.update_url)

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def current_ip(self) -> str | None:
        await self.start()
        assert self._session is not None
        try:
            async with self._session.get(CHECK_IP_URL) as resp:
                if resp.status == 200:
                    return (await resp.text()).strip()
        except aiohttp.ClientError:
            pass
        return None

    async def update(self, force: bool = False) -> tuple[bool, str]:
        """Refresh the record. Returns (changed, message).

        The IP is checked first and the update skipped when unchanged — FreeDNS
        asks that you don't hammer the endpoint, and an unnecessary update is
        just noise.
        """
        if not self.configured:
            return False, "FREEDNS_UPDATE_URL isn't set."

        ip = await self.current_ip()
        if ip and ip == self._last_ip and not force:
            return False, f"IP unchanged ({ip})."

        await self.start()
        assert self._session is not None
        try:
            async with self._session.get(self.update_url) as resp:
                body = (await resp.text()).strip()
                if resp.status != 200:
                    return False, f"FreeDNS returned HTTP {resp.status}."
        except aiohttp.ClientError as exc:
            return False, f"Couldn't reach FreeDNS: {exc}"

        self._last_ip = ip
        log.info("FreeDNS updated (%s): %s", ip or "unknown ip", body[:120])
        return True, body[:200] or "Updated."
