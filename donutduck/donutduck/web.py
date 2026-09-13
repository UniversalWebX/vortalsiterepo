"""Web dashboard, served alongside the bot.

Login is Discord OAuth2 — the same application the bot already uses, so no new
credentials beyond a client secret. That matters because the alternative
(a shared password) can't tell who someone is, and this dashboard shows ticket
contents and application answers.

Access rules: you only see a server if you have **Manage Server** there *and*
the bot is in it. Guild permissions are read from Discord's own
`/users/@me/guilds` response rather than trusted from the browser.

Sessions are signed cookies (itsdangerous-style HMAC, implemented here to
avoid another dependency). The cookie holds a user id and an expiry; tampering
invalidates the signature.

This is deliberately read-mostly. It shows what's happening and toggles a few
switches; destructive operations stay in Discord where the audit trail is.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

log = logging.getLogger("donutduck.web")

DISCORD_API = "https://discord.com/api/v10"
OAUTH_AUTHORIZE = "https://discord.com/oauth2/authorize"
OAUTH_TOKEN = f"{DISCORD_API}/oauth2/token"

SESSION_COOKIE = "donutduck_session"
SESSION_TTL = 7 * 86400
MANAGE_GUILD = 0x20
ADMINISTRATOR = 0x8


# --------------------------------------------------------------- sessions

def sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{digest}"


def unsign(token: str, secret: str) -> str | None:
    if not token or "." not in token:
        return None
    payload, _, digest = token.rpartition(".")
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # Constant-time compare so a timing attack can't recover the signature.
    if not hmac.compare_digest(digest, expected):
        return None
    return payload


def make_session(user_id: int, secret: str) -> str:
    return sign(f"{user_id}:{int(time.time()) + SESSION_TTL}", secret)


def read_session(token: str, secret: str) -> int | None:
    payload = unsign(token, secret)
    if not payload:
        return None
    try:
        user_id, expires = payload.split(":")
        if float(expires) < time.time():
            return None
        return int(user_id)
    except ValueError:
        return None


# ------------------------------------------------------------------ views

CSS = """
:root{--blue:#3B82F6;--pink:#FF4FA3;--yellow:#FFCE3B;--ink:#0f1522;--card:#182135;
--line:#26314d;--text:#E6ECFF;--muted:#93A3C8}
*{box-sizing:border-box}
body{margin:0;background:var(--ink);color:var(--text);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
header{background:linear-gradient(90deg,var(--blue),var(--pink) 55%,var(--yellow));
padding:2px}
header .bar{background:var(--ink);padding:14px 22px;display:flex;
align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:19px;margin:0}h2{font-size:16px;margin:0 0 12px}
.wrap{max-width:1080px;margin:0 auto;padding:26px 22px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card.b{border-top:3px solid var(--blue)}.card.p{border-top:3px solid var(--pink)}
.card.y{border-top:3px solid var(--yellow)}
.stat{font-size:30px;font-weight:700;margin:2px 0}
.muted{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);
vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.04em}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;
font-weight:600}
.open{background:rgba(59,130,246,.18);color:#9CC4FF}
.closed{background:rgba(147,163,200,.15);color:var(--muted)}
.pending{background:rgba(255,206,59,.16);color:var(--yellow)}
.btn{display:inline-block;background:var(--blue);color:#fff;padding:9px 16px;
border-radius:9px;font-weight:600;border:0;cursor:pointer;font-size:14px}
.btn.pink{background:var(--pink)}
.avatar{width:34px;height:34px;border-radius:50%}
.spacer{flex:1}
nav a{margin-right:16px;font-weight:600;color:var(--muted)}
nav a.on{color:var(--text);border-bottom:2px solid var(--pink);padding-bottom:3px}
.empty{color:var(--muted);padding:22px;text-align:center}
"""


def page(title: str, body: str, user: dict | None = None, nav: str = "") -> web.Response:
    avatar = ""
    if user:
        icon = (
            f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png?size=64"
            if user.get("avatar")
            else "https://cdn.discordapp.com/embed/avatars/0.png"
        )
        avatar = (
            f'<img class="avatar" src="{icon}" alt="">'
            f'<span>{user["username"]}</span>'
            f'<a href="/logout" class="muted">Log out</a>'
        )
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · DonutDuck</title><style>{CSS}</style></head><body>
<header><div class="bar"><h1>🍩🦆 DonutDuck</h1>
<nav>{nav}</nav><span class="spacer"></span>{avatar}</div></header>
<div class="wrap">{body}</div></body></html>"""
    return web.Response(text=html, content_type="text/html")


def esc(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ------------------------------------------------------------------ server

class Dashboard:
    def __init__(self, bot, *, client_id, client_secret, base_url, secret_key, port):
        self.bot = bot
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = (base_url or "").rstrip("/")
        self.secret_key = secret_key or secrets.token_hex(32)
        self.port = port
        self.runner: web.AppRunner | None = None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.base_url)

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/callback"

    # -------------------------------------------------------------- helpers

    async def current_user(self, request: web.Request) -> dict | None:
        token = request.cookies.get(SESSION_COOKIE, "")
        user_id = read_session(token, self.secret_key)
        if user_id is None:
            return None
        return request.app["users"].get(user_id)

    async def visible_guilds(self, user: dict) -> list:
        """Guilds where the user manages the server and the bot is present."""
        out = []
        bot_guilds = {g.id: g for g in self.bot.guilds}
        for entry in user.get("guilds", []):
            gid = int(entry["id"])
            perms = int(entry.get("permissions", 0))
            if not (perms & MANAGE_GUILD or perms & ADMINISTRATOR):
                continue
            if gid in bot_guilds:
                out.append(bot_guilds[gid])
        return out

    async def guild_or_403(self, request: web.Request, user: dict):
        gid = int(request.match_info["guild_id"])
        for guild in await self.visible_guilds(user):
            if guild.id == gid:
                return guild
        raise web.HTTPForbidden(text="You don't manage that server.")

    # --------------------------------------------------------------- routes

    async def index(self, request: web.Request):
        user = await self.current_user(request)
        if user is None:
            body = """<div class="card b"><h2>Sign in</h2>
<p class="muted">Log in with Discord to manage the servers you administrate.</p>
<p><a class="btn" href="/login">Log in with Discord</a></p></div>"""
            return page("Login", body)

        guilds = await self.visible_guilds(user)
        if not guilds:
            return page(
                "Servers",
                '<div class="card"><div class="empty">No servers found where you have '
                "Manage Server and DonutDuck is present.</div></div>",
                user,
            )

        cards = []
        for guild in guilds:
            counts = await self.bot.db.guild_counts(guild.id)
            icon = guild.icon.url if guild.icon else ""
            badge = f'<img class="avatar" src="{esc(icon)}" alt=""> ' if icon else ""
            cards.append(
                f'<div class="card b"><h2>{badge}{esc(guild.name)}</h2>'
                f'<div class="muted">{guild.member_count:,} members</div>'
                f'<p class="muted">{counts["open_tickets"]} open tickets · '
                f'{counts["pending_applications"]} applications</p>'
                f'<a class="btn" href="/g/{guild.id}">Manage</a></div>'
            )
        return page("Servers", f'<div class="grid">{"".join(cards)}</div>', user)

    async def login(self, request: web.Request):
        state = secrets.token_urlsafe(16)
        request.app["states"][state] = time.time() + 600
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "identify guilds",
            "state": state,
        }
        raise web.HTTPFound(f"{OAUTH_AUTHORIZE}?{urlencode(params)}")

    async def callback(self, request: web.Request):
        code = request.query.get("code")
        state = request.query.get("state", "")

        # State check: without it, a third-party site could walk someone
        # through a login they didn't intend to start.
        expires = request.app["states"].pop(state, None)
        if not code or expires is None or expires < time.time():
            raise web.HTTPBadRequest(text="Invalid or expired login attempt.")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                OAUTH_TOKEN,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status != 200:
                    raise web.HTTPBadRequest(text="Discord rejected the login.")
                token = (await resp.json())["access_token"]

            headers = {"Authorization": f"Bearer {token}"}
            async with session.get(f"{DISCORD_API}/users/@me", headers=headers) as resp:
                profile = await resp.json()
            async with session.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as resp:
                guilds = await resp.json()

        user_id = int(profile["id"])
        request.app["users"][user_id] = {
            "id": profile["id"],
            "username": profile.get("global_name") or profile["username"],
            "avatar": profile.get("avatar"),
            "guilds": guilds if isinstance(guilds, list) else [],
        }

        response = web.HTTPFound("/")
        response.set_cookie(
            SESSION_COOKIE,
            make_session(user_id, self.secret_key),
            max_age=SESSION_TTL,
            httponly=True,
            samesite="Lax",
            secure=self.base_url.startswith("https"),
        )
        raise response

    async def logout(self, request: web.Request):
        response = web.HTTPFound("/")
        response.del_cookie(SESSION_COOKIE)
        raise response

    async def guild_view(self, request: web.Request):
        user = await self.current_user(request)
        if user is None:
            raise web.HTTPFound("/login")
        guild = await self.guild_or_403(request, user)

        counts = await self.bot.db.guild_counts(guild.id)
        tickets = await self.bot.db.guild_tickets(guild.id, "open")
        applications = await self.bot.db.list_applications(guild.id, "pending")
        giveaways = await self.bot.db.active_giveaways(guild.id)
        streams = await self.bot.db.guild_streams(guild.id)

        stats = "".join(
            f'<div class="card {cls}"><div class="muted">{label}</div>'
            f'<div class="stat">{value}</div></div>'
            for label, value, cls in [
                ("Open tickets", counts["open_tickets"], "b"),
                ("Pending applications", counts["pending_applications"], "y"),
                ("Running giveaways", counts["active_giveaways"], "p"),
                ("Stat trackers", counts["trackers"], "b"),
                ("Streamers watched", counts["streams"], "p"),
                ("Tickets all time", counts["total_tickets"], "y"),
            ]
        )

        ticket_rows = "".join(
            f"<tr><td>#{t['number']:04d}</td><td>{esc(t['type_key'])}</td>"
            f"<td>{esc((t.get('reason') or '—')[:70])}</td>"
            f"<td><span class='pill open'>open</span></td></tr>"
            for t in tickets[:15]
        ) or '<tr><td colspan="4" class="empty">No open tickets</td></tr>'

        app_rows = "".join(
            f"<tr><td>#{a['id']}</td><td>{esc(a['form_key'])}</td>"
            f"<td>&lt;@{a['user_id']}&gt;</td>"
            f"<td><span class='pill pending'>pending</span></td></tr>"
            for a in applications[:15]
        ) or '<tr><td colspan="4" class="empty">Nothing pending</td></tr>'

        # Entry counts need an await each, so build this with a loop — an
        # await can't live inside a generator expression passed to join().
        gw_cells = []
        for giveaway in giveaways[:10]:
            entries = await self.bot.db.entry_count(giveaway["id"])
            gw_cells.append(
                f"<tr><td>{esc(giveaway['prize'])}</td>"
                f"<td>{giveaway['winner_count']}</td><td>{entries}</td></tr>"
            )
        gw_rows = "".join(gw_cells) or (
            '<tr><td colspan="3" class="empty">None running</td></tr>'
        )

        stream_rows = "".join(
            f"<tr><td>{esc(s['login'])}</td>"
            f"<td>{'🔴 live' if s['is_live'] else '⚫ offline'}</td></tr>"
            for s in streams[:10]
        ) or '<tr><td colspan="2" class="empty">None watched</td></tr>'

        body = f"""
<p><a href="/" class="muted">← All servers</a></p>
<h2>{esc(guild.name)}</h2>
<div class="grid">{stats}</div>
<div class="card" style="margin-top:20px"><h2>Open tickets</h2>
<table><tr><th>#</th><th>Type</th><th>Reason</th><th>Status</th></tr>
{ticket_rows}</table></div>
<div class="card" style="margin-top:16px"><h2>Pending applications</h2>
<table><tr><th>#</th><th>Form</th><th>Applicant</th><th>Status</th></tr>
{app_rows}</table></div>
<div class="card" style="margin-top:16px"><h2>Giveaways</h2>
<table><tr><th>Prize</th><th>Winners</th><th>Entries</th></tr>{gw_rows}</table></div>
<div class="card" style="margin-top:16px"><h2>Twitch</h2>
<table><tr><th>Streamer</th><th>Status</th></tr>{stream_rows}</table></div>
<p class="muted" style="margin-top:18px">This dashboard is read-only by design —
actions stay in Discord, where they're attributable and logged.</p>
"""
        return page(guild.name, body, user)

    async def health(self, request: web.Request):
        return web.json_response(
            {
                "status": "ok",
                "guilds": len(self.bot.guilds),
                "latency_ms": round(self.bot.latency * 1000),
            }
        )

    # ---------------------------------------------------------- lifecycle

    def build_app(self) -> web.Application:
        app = web.Application()
        app["users"] = {}
        app["states"] = {}
        app.add_routes(
            [
                web.get("/", self.index),
                web.get("/login", self.login),
                web.get("/callback", self.callback),
                web.get("/logout", self.logout),
                web.get("/g/{guild_id}", self.guild_view),
                web.get("/health", self.health),
            ]
        )
        return app

    async def start(self) -> None:
        if not self.configured:
            log.info(
                "Dashboard disabled — set DASHBOARD_BASE_URL, DISCORD_CLIENT_ID "
                "and DISCORD_CLIENT_SECRET to enable it."
            )
            return
        self.runner = web.AppRunner(self.build_app())
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()
        log.info("Dashboard listening on port %s (public URL %s)", self.port, self.base_url)

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
