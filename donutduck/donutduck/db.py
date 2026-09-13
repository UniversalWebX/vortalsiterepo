"""SQLite persistence for trackers, guild config and partnerships.

One file, no server to run. Everything is awaited so it never blocks the
gateway heartbeat.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiosqlite

log = logging.getLogger("donutduck.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trackers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    player      TEXT    NOT NULL,
    stat        TEXT    NOT NULL,
    created_at  REAL    NOT NULL,
    last_run    REAL    NOT NULL DEFAULT 0,
    last_value  REAL,
    UNIQUE (guild_id, player, stat)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    player   TEXT NOT NULL,
    stat     TEXT NOT NULL,
    value    REAL NOT NULL,
    taken_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots ON snapshots (player, stat, taken_at);

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id          INTEGER PRIMARY KEY,
    partners_enabled  INTEGER NOT NULL DEFAULT 0,
    partner_channel   INTEGER,
    invite_url        TEXT,
    description       TEXT,
    tracker_channel   INTEGER
);

CREATE TABLE IF NOT EXISTS giveaways (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    channel_id    INTEGER NOT NULL,
    message_id    INTEGER,
    prize         TEXT    NOT NULL,
    description   TEXT,
    winner_count  INTEGER NOT NULL DEFAULT 1,
    host_id       INTEGER NOT NULL,
    required_role INTEGER,
    created_at    REAL    NOT NULL,
    ends_at       REAL    NOT NULL,
    ended         INTEGER NOT NULL DEFAULT 0,
    mode          TEXT    NOT NULL DEFAULT 'normal',  -- normal|split_steal|double
    claim_hours   INTEGER NOT NULL DEFAULT 24,
    min_account_days INTEGER NOT NULL DEFAULT 0,
    bonus_role    INTEGER,
    bonus_entries INTEGER NOT NULL DEFAULT 1,
    cancelled     INTEGER NOT NULL DEFAULT 0,
    value         REAL,              -- numeric worth, so "double" means something
    parent_id     INTEGER,           -- giveaway this was doubled from
    double_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_gw_open ON giveaways (ended, ends_at);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    entered_at  REAL    NOT NULL,
    PRIMARY KEY (giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaway_winners (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    won_at      REAL    NOT NULL,
    ticket_id   INTEGER,
    claimed     INTEGER NOT NULL DEFAULT 0,
    choice      TEXT,                -- split|steal, or keep|gamble
    payout      TEXT,                -- what they actually walk away with
    resolved    INTEGER NOT NULL DEFAULT 0,
    expired     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ticket_types (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    key           TEXT    NOT NULL,
    label         TEXT    NOT NULL,
    emoji         TEXT,
    description   TEXT,
    staff_role_id INTEGER,
    category_id   INTEGER,
    questions     TEXT,               -- JSON list of prompt strings
    enabled       INTEGER NOT NULL DEFAULT 1,
    is_builtin    INTEGER NOT NULL DEFAULT 0,
    hidden        INTEGER NOT NULL DEFAULT 0,   -- not shown on the panel
    position      INTEGER NOT NULL DEFAULT 0,
    open_title    TEXT,          -- custom opening message
    open_message  TEXT,
    open_color    TEXT,
    open_image    TEXT,
    open_footer   TEXT,
    ping_staff    INTEGER NOT NULL DEFAULT 1,
    ping_user     INTEGER NOT NULL DEFAULT 1,
    show_answers  INTEGER NOT NULL DEFAULT 1,
    UNIQUE (guild_id, key)
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    number      INTEGER NOT NULL,
    type_key    TEXT    NOT NULL,
    user_id     INTEGER NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open',   -- open | closed
    claimed_by  INTEGER,
    giveaway_id INTEGER,
    answers     TEXT,
    reason      TEXT,
    ign         TEXT,
    created_at  REAL    NOT NULL,
    closed_at   REAL,
    closed_by   INTEGER,
    close_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_channel ON tickets (channel_id);

CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id        INTEGER PRIMARY KEY,
    category_id     INTEGER,
    log_channel_id  INTEGER,
    panel_channel   INTEGER,
    panel_message   INTEGER,
    next_number     INTEGER NOT NULL DEFAULT 1,
    max_open        INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS guild_profile (
    guild_id   INTEGER PRIMARY KEY,
    avatar_url TEXT,          -- source URL, for /serverprofile view
    nickname   TEXT,
    updated_at REAL,
    updated_by INTEGER
);

CREATE TABLE IF NOT EXISTS stream_subs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    channel_id    INTEGER NOT NULL,
    platform      TEXT    NOT NULL DEFAULT 'twitch',
    login         TEXT    NOT NULL,            -- twitch username, lowercased
    mention_role  INTEGER,
    message       TEXT,
    last_stream   TEXT,                        -- stream id, stops repeat pings
    is_live       INTEGER NOT NULL DEFAULT 0,
    added_by      INTEGER,
    created_at    REAL    NOT NULL,
    UNIQUE (guild_id, platform, login)
);

CREATE TABLE IF NOT EXISTS application_forms (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id       INTEGER NOT NULL,
    key            TEXT    NOT NULL,
    label          TEXT    NOT NULL,
    description    TEXT,
    emoji          TEXT,
    questions      TEXT,          -- JSON list, up to 25
    review_channel INTEGER,
    accept_role    INTEGER,
    enabled        INTEGER NOT NULL DEFAULT 1,
    cooldown_days  INTEGER NOT NULL DEFAULT 14,
    position       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (guild_id, key)
);

CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    form_key    TEXT    NOT NULL,
    user_id     INTEGER NOT NULL,
    answers     TEXT    NOT NULL,      -- JSON {question: answer}
    status      TEXT    NOT NULL DEFAULT 'pending',
    reviewer_id INTEGER,
    reason      TEXT,
    message_id  INTEGER,
    created_at  REAL    NOT NULL,
    decided_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_apps ON applications (guild_id, form_key, user_id, status);

CREATE TABLE IF NOT EXISTS ticket_panels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    key         TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    description TEXT,
    type_keys   TEXT,                -- JSON list; empty/null = every visible type
    channel_id  INTEGER,
    message_id  INTEGER,
    placeholder TEXT,
    UNIQUE (guild_id, key)
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id         INTEGER PRIMARY KEY,
    welcome_channel  INTEGER,
    welcome_message  TEXT,
    goodbye_channel  INTEGER,
    goodbye_message  TEXT,
    autorole         INTEGER,
    starboard_channel INTEGER,
    starboard_stars  INTEGER NOT NULL DEFAULT 3,
    starboard_emoji  TEXT NOT NULL DEFAULT '⭐',
    vouch_channel    INTEGER,
    default_claim_hours INTEGER NOT NULL DEFAULT 24,
    staff_roles      TEXT,          -- JSON list of role ids
    legit_channel    INTEGER,
    activity_channel INTEGER,
    strike_limit     INTEGER NOT NULL DEFAULT 3,
    giveaway_cap     REAL
);

CREATE TABLE IF NOT EXISTS strikes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    reason     TEXT,
    issued_by  INTEGER,
    check_id   INTEGER,
    created_at REAL NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_strikes ON strikes (guild_id, user_id, active);

CREATE TABLE IF NOT EXISTS activity_checks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    started_by INTEGER NOT NULL,
    deadline   REAL NOT NULL,
    created_at REAL NOT NULL,
    closed     INTEGER NOT NULL DEFAULT 0,
    strike_on_miss INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS activity_responses (
    check_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    responded_at REAL NOT NULL,
    PRIMARY KEY (check_id, user_id)
);

CREATE TABLE IF NOT EXISTS legit_votes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    giveaway_id INTEGER,
    subject_id  INTEGER,
    channel_id  INTEGER NOT NULL,
    message_id  INTEGER,
    prize       TEXT,
    created_at  REAL NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS legit_vote_entries (
    vote_id   INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    choice    TEXT NOT NULL,          -- legit | not_legit
    voted_at  REAL NOT NULL,
    PRIMARY KEY (vote_id, user_id)
);

CREATE TABLE IF NOT EXISTS vouches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    from_user   INTEGER NOT NULL,
    to_user     INTEGER NOT NULL,
    message     TEXT,
    source      TEXT NOT NULL DEFAULT 'command',   -- command | giveaway
    giveaway_id INTEGER,
    message_id  INTEGER,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vouches ON vouches (guild_id, to_user);

CREATE TABLE IF NOT EXISTS reaction_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    key         TEXT    NOT NULL,
    title       TEXT,
    style       TEXT    NOT NULL DEFAULT 'dropdown',   -- dropdown | buttons
    options     TEXT    NOT NULL,                      -- JSON [{role_id,label,emoji,description}]
    max_choices INTEGER NOT NULL DEFAULT 0,            -- 0 = unlimited
    UNIQUE (guild_id, key)
);

CREATE TABLE IF NOT EXISTS starboard_posts (
    source_id INTEGER PRIMARY KEY,
    guild_id  INTEGER NOT NULL,
    post_id   INTEGER NOT NULL,
    stars     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER,
    channel_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    text       TEXT    NOT NULL,
    remind_at  REAL    NOT NULL,
    created_at REAL    NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reminders ON reminders (done, remind_at);

CREATE TABLE IF NOT EXISTS scripts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    code        TEXT    NOT NULL,
    description TEXT,
    created_by  INTEGER NOT NULL,
    created_at  REAL    NOT NULL,
    updated_at  REAL,
    uses        INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    staff_only  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (guild_id, name)
);

CREATE TABLE IF NOT EXISTS partnerships (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_a     INTEGER NOT NULL,
    guild_b     INTEGER NOT NULL,
    status      TEXT    NOT NULL,          -- pending | accepted | declined
    requested_by INTEGER NOT NULL,
    created_at  REAL    NOT NULL,
    UNIQUE (guild_a, guild_b)
);
"""


class Database:
    def __init__(self, path: str = "donutduck.db"):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        """Add columns introduced after a database was first created.

        CREATE TABLE IF NOT EXISTS silently does nothing when the table already
        exists, so new columns need an explicit ALTER. Each is guarded by a
        check against PRAGMA table_info so this is safe to run on every start.
        """
        wanted = {
            "tickets": [("reason", "TEXT"), ("ign", "TEXT")],
            "activity_checks": [("strike_on_miss", "INTEGER NOT NULL DEFAULT 1")],
            "giveaways": [
                ("mode", "TEXT NOT NULL DEFAULT 'normal'"),
                ("claim_hours", "INTEGER NOT NULL DEFAULT 24"),
                ("min_account_days", "INTEGER NOT NULL DEFAULT 0"),
                ("bonus_role", "INTEGER"),
                ("bonus_entries", "INTEGER NOT NULL DEFAULT 1"),
                ("cancelled", "INTEGER NOT NULL DEFAULT 0"),
                ("value", "REAL"),
                ("parent_id", "INTEGER"),
                ("double_count", "INTEGER NOT NULL DEFAULT 0"),
            ],
            "guild_settings": [
                ("vouch_channel", "INTEGER"),
                ("default_claim_hours", "INTEGER NOT NULL DEFAULT 24"),
                ("staff_roles", "TEXT"),
                ("legit_channel", "INTEGER"),
                ("activity_channel", "INTEGER"),
                ("strike_limit", "INTEGER NOT NULL DEFAULT 3"),
                ("giveaway_cap", "REAL"),
            ],
            "giveaway_winners": [
                ("claimed", "INTEGER NOT NULL DEFAULT 0"),
                ("choice", "TEXT"),
                ("payout", "TEXT"),
                ("resolved", "INTEGER NOT NULL DEFAULT 0"),
                ("expired", "INTEGER NOT NULL DEFAULT 0"),
            ],
            "ticket_types": [
                ("open_title", "TEXT"),
                ("open_message", "TEXT"),
                ("open_color", "TEXT"),
                ("open_image", "TEXT"),
                ("open_footer", "TEXT"),
                ("ping_staff", "INTEGER NOT NULL DEFAULT 1"),
                ("ping_user", "INTEGER NOT NULL DEFAULT 1"),
                ("show_answers", "INTEGER NOT NULL DEFAULT 1"),
            ],
        }
        for table, columns in wanted.items():
            cur = await self.db.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in await cur.fetchall()}
            for name, coltype in columns:
                if name not in existing:
                    await self.db.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {coltype}"
                    )
                    log.info("Migrated: added %s.%s", table, name)
        await self.db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database.connect() was never awaited")
        return self._db

    # ------------------------------------------------------------ trackers

    async def add_tracker(
        self, guild_id: int, channel_id: int, user_id: int, player: str, stat: str
    ) -> bool:
        """Returns False if this guild already tracks that player+stat."""
        try:
            await self.db.execute(
                "INSERT INTO trackers (guild_id, channel_id, user_id, player, stat, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, channel_id, user_id, player, stat, time.time()),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_tracker(self, guild_id: int, player: str, stat: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM trackers WHERE guild_id = ? AND lower(player) = lower(?) AND stat = ?",
            (guild_id, player, stat),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def guild_trackers(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM trackers WHERE guild_id = ? ORDER BY player, stat", (guild_id,)
        )
        return list(await cur.fetchall())

    async def due_trackers(self, interval: float) -> list[aiosqlite.Row]:
        cutoff = time.time() - interval
        cur = await self.db.execute(
            "SELECT * FROM trackers WHERE last_run <= ?", (cutoff,)
        )
        return list(await cur.fetchall())

    async def all_trackers(self) -> list[aiosqlite.Row]:
        cur = await self.db.execute("SELECT * FROM trackers")
        return list(await cur.fetchall())

    async def mark_run(self, tracker_id: int, value: float | None) -> None:
        await self.db.execute(
            "UPDATE trackers SET last_run = ?, last_value = ? WHERE id = ?",
            (time.time(), value, tracker_id),
        )
        await self.db.commit()

    async def delete_tracker_by_id(self, tracker_id: int) -> None:
        await self.db.execute("DELETE FROM trackers WHERE id = ?", (tracker_id,))
        await self.db.commit()

    # ----------------------------------------------------------- snapshots

    async def add_snapshot(
        self, player: str, stat: str, value: float, taken_at: float | None = None
    ) -> None:
        """`taken_at` defaults to now; pass it explicitly to backfill history."""
        await self.db.execute(
            "INSERT INTO snapshots (player, stat, value, taken_at) VALUES (?, ?, ?, ?)",
            (player.lower(), stat, value, taken_at if taken_at is not None else time.time()),
        )
        await self.db.commit()

    async def history(self, player: str, stat: str, limit: int = 20) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM snapshots WHERE player = ? AND stat = ?"
            " ORDER BY taken_at DESC LIMIT ?",
            (player.lower(), stat, limit),
        )
        return list(await cur.fetchall())

    async def prune_snapshots(self, keep_days: int = 90) -> int:
        cutoff = time.time() - keep_days * 86400
        cur = await self.db.execute("DELETE FROM snapshots WHERE taken_at < ?", (cutoff,))
        await self.db.commit()
        return cur.rowcount

    # -------------------------------------------------------- guild config

    async def get_config(self, guild_id: int) -> dict[str, Any]:
        cur = await self.db.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "partners_enabled": 0,
            "partner_channel": None,
            "invite_url": None,
            "description": None,
            "tracker_channel": None,
        }

    async def set_config(self, guild_id: int, **fields: Any) -> None:
        allowed = {
            "partners_enabled",
            "partner_channel",
            "invite_url",
            "description",
            "tracker_channel",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        await self.db.execute(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,)
        )
        assignments = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(
            f"UPDATE guild_config SET {assignments} WHERE guild_id = ?",
            (*fields.values(), guild_id),
        )
        await self.db.commit()

    async def partner_enabled_guilds(self) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT * FROM guild_config WHERE partners_enabled = 1"
            " AND partner_channel IS NOT NULL"
        )
        return list(await cur.fetchall())

    # ------------------------------------------------------- partnerships

    @staticmethod
    def _pair(a: int, b: int) -> tuple[int, int]:
        """Store pairs in a stable order so (a,b) and (b,a) are one row."""
        return (a, b) if a < b else (b, a)

    async def create_request(self, requester: int, target: int, user_id: int) -> str:
        a, b = self._pair(requester, target)
        cur = await self.db.execute(
            "SELECT status FROM partnerships WHERE guild_a = ? AND guild_b = ?", (a, b)
        )
        row = await cur.fetchone()
        if row:
            if row["status"] == "accepted":
                return "already_partners"
            if row["status"] == "pending":
                return "already_pending"
            await self.db.execute(
                "DELETE FROM partnerships WHERE guild_a = ? AND guild_b = ?", (a, b)
            )
        await self.db.execute(
            "INSERT INTO partnerships (guild_a, guild_b, status, requested_by, created_at)"
            " VALUES (?, ?, 'pending', ?, ?)",
            (a, b, user_id, time.time()),
        )
        await self.db.commit()
        return "created"

    async def set_partnership_status(self, g1: int, g2: int, status: str) -> bool:
        a, b = self._pair(g1, g2)
        cur = await self.db.execute(
            "UPDATE partnerships SET status = ? WHERE guild_a = ? AND guild_b = ?",
            (status, a, b),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def remove_partnership(self, g1: int, g2: int) -> bool:
        a, b = self._pair(g1, g2)
        cur = await self.db.execute(
            "DELETE FROM partnerships WHERE guild_a = ? AND guild_b = ?", (a, b)
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def partnerships_for(self, guild_id: int, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM partnerships WHERE (guild_a = ? OR guild_b = ?)"
        params: list[Any] = [guild_id, guild_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        cur = await self.db.execute(query, params)
        rows = await cur.fetchall()
        out = []
        for row in rows:
            other = row["guild_b"] if row["guild_a"] == guild_id else row["guild_a"]
            out.append(
                {
                    "other_guild": other,
                    "status": row["status"],
                    "requested_by": row["requested_by"],
                    "created_at": row["created_at"],
                    "incoming": row["requested_by"] and other != guild_id,
                }
            )
        return out

    async def pending_between(self, g1: int, g2: int) -> dict | None:
        a, b = self._pair(g1, g2)
        cur = await self.db.execute(
            "SELECT * FROM partnerships WHERE guild_a = ? AND guild_b = ? AND status = 'pending'",
            (a, b),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------ giveaways

    async def create_giveaway(
        self,
        guild_id: int,
        channel_id: int,
        prize: str,
        winner_count: int,
        host_id: int,
        ends_at: float,
        description: str | None = None,
        required_role: int | None = None,
        mode: str = "normal",
        claim_hours: int = 24,
        min_account_days: int = 0,
        bonus_role: int | None = None,
        bonus_entries: int = 1,
        value: float | None = None,
        parent_id: int | None = None,
        double_count: int = 0,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, prize, description, winner_count,"
            " host_id, required_role, created_at, ends_at, mode, claim_hours,"
            " min_account_days, bonus_role, bonus_entries, value, parent_id,"
            " double_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                prize,
                description,
                winner_count,
                host_id,
                required_role,
                time.time(),
                ends_at,
                mode,
                claim_hours,
                min_account_days,
                bonus_role,
                bonus_entries,
                value,
                parent_id,
                double_count,
            ),
        )
        await self.db.commit()
        return cur.lastrowid

    async def set_giveaway_message(self, giveaway_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id)
        )
        await self.db.commit()

    async def get_giveaway(self, giveaway_id: int) -> dict | None:
        cur = await self.db.execute("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_giveaway_by_message(self, message_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM giveaways WHERE message_id = ?", (message_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def active_giveaways(self, guild_id: int | None = None) -> list[dict]:
        if guild_id is None:
            cur = await self.db.execute("SELECT * FROM giveaways WHERE ended = 0")
        else:
            cur = await self.db.execute(
                "SELECT * FROM giveaways WHERE ended = 0 AND guild_id = ?", (guild_id,)
            )
        return [dict(r) for r in await cur.fetchall()]

    async def due_giveaways(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM giveaways WHERE ended = 0 AND ends_at <= ?", (time.time(),)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def mark_giveaway_ended(self, giveaway_id: int) -> None:
        await self.db.execute(
            "UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,)
        )
        await self.db.commit()

    async def add_entry(self, giveaway_id: int, user_id: int) -> bool:
        """False if they'd already entered."""
        try:
            await self.db.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id, entered_at)"
                " VALUES (?, ?, ?)",
                (giveaway_id, user_id, time.time()),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_entry(self, giveaway_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def entries(self, giveaway_id: int) -> list[int]:
        cur = await self.db.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        )
        return [r["user_id"] for r in await cur.fetchall()]

    async def entry_count(self, giveaway_id: int) -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) AS n FROM giveaway_entries WHERE giveaway_id = ?",
            (giveaway_id,),
        )
        row = await cur.fetchone()
        return row["n"] if row else 0

    async def record_winners(self, giveaway_id: int, user_ids: list[int]) -> None:
        await self.db.executemany(
            "INSERT INTO giveaway_winners (giveaway_id, user_id, won_at) VALUES (?, ?, ?)",
            [(giveaway_id, uid, time.time()) for uid in user_ids],
        )
        await self.db.commit()

    async def previous_winners(self, giveaway_id: int) -> list[int]:
        cur = await self.db.execute(
            "SELECT user_id FROM giveaway_winners WHERE giveaway_id = ?", (giveaway_id,)
        )
        return [r["user_id"] for r in await cur.fetchall()]

    async def link_winner_ticket(
        self, giveaway_id: int, user_id: int, ticket_id: int
    ) -> None:
        await self.db.execute(
            "UPDATE giveaway_winners SET ticket_id = ? WHERE giveaway_id = ? AND user_id = ?",
            (ticket_id, giveaway_id, user_id),
        )
        await self.db.commit()

    # -------------------------------------------------------- ticket types

    async def add_ticket_type(
        self,
        guild_id: int,
        key: str,
        label: str,
        *,
        emoji: str | None = None,
        description: str | None = None,
        staff_role_id: int | None = None,
        category_id: int | None = None,
        questions: str | None = None,
        is_builtin: int = 0,
        hidden: int = 0,
        position: int = 0,
    ) -> bool:
        try:
            await self.db.execute(
                "INSERT INTO ticket_types (guild_id, key, label, emoji, description,"
                " staff_role_id, category_id, questions, is_builtin, hidden, position)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    key,
                    label,
                    emoji,
                    description,
                    staff_role_id,
                    category_id,
                    questions,
                    is_builtin,
                    hidden,
                    position,
                ),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_ticket_type(self, guild_id: int, key: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM ticket_types WHERE guild_id = ? AND key = ?", (guild_id, key)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def ticket_types(self, guild_id: int, only_enabled: bool = False) -> list[dict]:
        query = "SELECT * FROM ticket_types WHERE guild_id = ?"
        if only_enabled:
            query += " AND enabled = 1"
        query += " ORDER BY position, id"
        cur = await self.db.execute(query, (guild_id,))
        return [dict(r) for r in await cur.fetchall()]

    async def update_ticket_type(self, guild_id: int, key: str, **fields) -> bool:
        allowed = {
            "label",
            "emoji",
            "description",
            "staff_role_id",
            "category_id",
            "questions",
            "enabled",
            "hidden",
            "position",
            "open_title",
            "open_message",
            "open_color",
            "open_image",
            "open_footer",
            "ping_staff",
            "ping_user",
            "show_answers",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return False
        assignments = ", ".join(f"{k} = ?" for k in fields)
        cur = await self.db.execute(
            f"UPDATE ticket_types SET {assignments} WHERE guild_id = ? AND key = ?",
            (*fields.values(), guild_id, key),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def delete_ticket_type(self, guild_id: int, key: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM ticket_types WHERE guild_id = ? AND key = ? AND is_builtin = 0",
            (guild_id, key),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------- tickets

    async def ticket_config(self, guild_id: int) -> dict:
        cur = await self.db.execute(
            "SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "category_id": None,
            "log_channel_id": None,
            "panel_channel": None,
            "panel_message": None,
            "next_number": 1,
            "max_open": 3,
        }

    async def set_ticket_config(self, guild_id: int, **fields) -> None:
        allowed = {
            "category_id",
            "log_channel_id",
            "panel_channel",
            "panel_message",
            "next_number",
            "max_open",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        await self.db.execute(
            "INSERT OR IGNORE INTO ticket_config (guild_id) VALUES (?)", (guild_id,)
        )
        assignments = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(
            f"UPDATE ticket_config SET {assignments} WHERE guild_id = ?",
            (*fields.values(), guild_id),
        )
        await self.db.commit()

    async def next_ticket_number(self, guild_id: int) -> int:
        await self.db.execute(
            "INSERT OR IGNORE INTO ticket_config (guild_id) VALUES (?)", (guild_id,)
        )
        cur = await self.db.execute(
            "SELECT next_number FROM ticket_config WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        number = row["next_number"] if row else 1
        await self.db.execute(
            "UPDATE ticket_config SET next_number = ? WHERE guild_id = ?",
            (number + 1, guild_id),
        )
        await self.db.commit()
        return number

    async def create_ticket(
        self,
        guild_id: int,
        channel_id: int,
        number: int,
        type_key: str,
        user_id: int,
        giveaway_id: int | None = None,
        answers: str | None = None,
        reason: str | None = None,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, number, type_key, user_id,"
            " giveaway_id, answers, reason, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                number,
                type_key,
                user_id,
                giveaway_id,
                answers,
                reason,
                time.time(),
            ),
        )
        await self.db.commit()
        return cur.lastrowid

    async def ticket_by_channel(self, channel_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def open_tickets_for(self, guild_id: int, user_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
            (guild_id, user_id),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def open_ticket_of_type(
        self, guild_id: int, user_id: int, type_key: str
    ) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND type_key = ?"
            " AND status = 'open'",
            (guild_id, user_id, type_key),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def guild_tickets(self, guild_id: int, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM tickets WHERE guild_id = ?"
        params: list = [guild_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY number DESC"
        cur = await self.db.execute(query, params)
        return [dict(r) for r in await cur.fetchall()]

    async def claim_ticket(self, channel_id: int, staff_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE tickets SET claimed_by = ? WHERE channel_id = ? AND status = 'open'",
            (staff_id, channel_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def close_ticket(
        self, channel_id: int, closed_by: int, reason: str | None = None
    ) -> bool:
        cur = await self.db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ?,"
            " close_reason = ? WHERE channel_id = ? AND status = 'open'",
            (time.time(), closed_by, reason, channel_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------- guild profile

    async def get_profile(self, guild_id: int) -> dict:
        cur = await self.db.execute(
            "SELECT * FROM guild_profile WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "avatar_url": None,
            "nickname": None,
            "updated_at": None,
            "updated_by": None,
        }

    async def set_profile(self, guild_id: int, **fields) -> None:
        allowed = {"avatar_url", "nickname", "updated_by"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        fields["updated_at"] = time.time()
        await self.db.execute(
            "INSERT OR IGNORE INTO guild_profile (guild_id) VALUES (?)", (guild_id,)
        )
        assignments = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(
            f"UPDATE guild_profile SET {assignments} WHERE guild_id = ?",
            (*fields.values(), guild_id),
        )
        await self.db.commit()

    async def clear_profile(self, guild_id: int) -> None:
        await self.db.execute(
            "DELETE FROM guild_profile WHERE guild_id = ?", (guild_id,)
        )
        await self.db.commit()

    # -------------------------------------------------------- stream subs

    async def add_stream(
        self,
        guild_id: int,
        channel_id: int,
        login: str,
        platform: str = "twitch",
        mention_role: int | None = None,
        message: str | None = None,
        added_by: int | None = None,
    ) -> bool:
        try:
            await self.db.execute(
                "INSERT INTO stream_subs (guild_id, channel_id, platform, login,"
                " mention_role, message, added_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    channel_id,
                    platform,
                    login.lower(),
                    mention_role,
                    message,
                    added_by,
                    time.time(),
                ),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_stream(self, guild_id: int, login: str, platform: str = "twitch") -> bool:
        cur = await self.db.execute(
            "DELETE FROM stream_subs WHERE guild_id = ? AND platform = ? AND login = ?",
            (guild_id, platform, login.lower()),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def guild_streams(self, guild_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM stream_subs WHERE guild_id = ? ORDER BY login", (guild_id,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def all_streams(self, platform: str = "twitch") -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM stream_subs WHERE platform = ?", (platform,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def set_stream_state(
        self, sub_id: int, is_live: bool, stream_id: str | None
    ) -> None:
        await self.db.execute(
            "UPDATE stream_subs SET is_live = ?, last_stream = ? WHERE id = ?",
            (1 if is_live else 0, stream_id, sub_id),
        )
        await self.db.commit()

    # ------------------------------------------------------- applications

    async def add_form(self, guild_id: int, key: str, label: str, **fields) -> bool:
        allowed = {
            "description",
            "emoji",
            "questions",
            "review_channel",
            "accept_role",
            "cooldown_days",
            "position",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        try:
            await self.db.execute(
                f"INSERT INTO application_forms (guild_id, key, label"
                f"{', ' + columns if columns else ''}) VALUES (?, ?, ?"
                f"{', ' + placeholders if placeholders else ''})",
                (guild_id, key, label, *fields.values()),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_form(self, guild_id: int, key: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM application_forms WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def forms(self, guild_id: int, only_enabled: bool = False) -> list[dict]:
        query = "SELECT * FROM application_forms WHERE guild_id = ?"
        if only_enabled:
            query += " AND enabled = 1"
        query += " ORDER BY position, id"
        cur = await self.db.execute(query, (guild_id,))
        return [dict(r) for r in await cur.fetchall()]

    async def update_form(self, guild_id: int, key: str, **fields) -> bool:
        allowed = {
            "label",
            "description",
            "emoji",
            "questions",
            "review_channel",
            "accept_role",
            "enabled",
            "cooldown_days",
            "position",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return False
        assignments = ", ".join(f"{k} = ?" for k in fields)
        cur = await self.db.execute(
            f"UPDATE application_forms SET {assignments} WHERE guild_id = ? AND key = ?",
            (*fields.values(), guild_id, key),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def delete_form(self, guild_id: int, key: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM application_forms WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def create_application(
        self, guild_id: int, form_key: str, user_id: int, answers: str
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO applications (guild_id, form_key, user_id, answers, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (guild_id, form_key, user_id, answers, time.time()),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_application(self, application_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_application_message(self, application_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE applications SET message_id = ? WHERE id = ?",
            (message_id, application_id),
        )
        await self.db.commit()

    async def decide_application(
        self, application_id: int, status: str, reviewer_id: int, reason: str | None
    ) -> bool:
        cur = await self.db.execute(
            "UPDATE applications SET status = ?, reviewer_id = ?, reason = ?,"
            " decided_at = ? WHERE id = ? AND status = 'pending'",
            (status, reviewer_id, reason, time.time(), application_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def pending_application(
        self, guild_id: int, form_key: str, user_id: int
    ) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM applications WHERE guild_id = ? AND form_key = ?"
            " AND user_id = ? AND status = 'pending'",
            (guild_id, form_key, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def last_application(
        self, guild_id: int, form_key: str, user_id: int
    ) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM applications WHERE guild_id = ? AND form_key = ? AND user_id = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (guild_id, form_key, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_applications(
        self, guild_id: int, status: str | None = None, form_key: str | None = None
    ) -> list[dict]:
        query = "SELECT * FROM applications WHERE guild_id = ?"
        params: list = [guild_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        if form_key:
            query += " AND form_key = ?"
            params.append(form_key)
        query += " ORDER BY created_at DESC"
        cur = await self.db.execute(query, params)
        return [dict(r) for r in await cur.fetchall()]

    # -------------------------------------------------------- ticket panels

    async def add_panel(self, guild_id: int, key: str, title: str, **fields) -> bool:
        allowed = {"description", "type_keys", "channel_id", "message_id", "placeholder"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        try:
            await self.db.execute(
                f"INSERT INTO ticket_panels (guild_id, key, title"
                f"{', ' + columns if columns else ''}) VALUES (?, ?, ?"
                f"{', ' + placeholders if placeholders else ''})",
                (guild_id, key, title, *fields.values()),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def get_panel(self, guild_id: int, ref: str | int) -> dict | None:
        """Look a panel up by its numeric id or its name — whichever the
        person used. Both are unique within a guild."""
        if str(ref).isdigit():
            cur = await self.db.execute(
                "SELECT * FROM ticket_panels WHERE guild_id = ? AND id = ?",
                (guild_id, int(ref)),
            )
            row = await cur.fetchone()
            if row:
                return dict(row)
        cur = await self.db.execute(
            "SELECT * FROM ticket_panels WHERE guild_id = ? AND key = ?",
            (guild_id, str(ref)),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def panels(self, guild_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM ticket_panels WHERE guild_id = ? ORDER BY id", (guild_id,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def update_panel(self, guild_id: int, ref: str | int, **fields) -> bool:
        allowed = {
            "title", "description", "type_keys", "channel_id", "message_id", "placeholder"
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return False
        panel = await self.get_panel(guild_id, ref)
        if panel is None:
            return False
        assignments = ", ".join(f"{k} = ?" for k in fields)
        cur = await self.db.execute(
            f"UPDATE ticket_panels SET {assignments} WHERE id = ?",
            (*fields.values(), panel["id"]),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def delete_panel(self, guild_id: int, ref: str | int) -> bool:
        panel = await self.get_panel(guild_id, ref)
        if panel is None:
            return False
        cur = await self.db.execute(
            "DELETE FROM ticket_panels WHERE id = ?", (panel["id"],)
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------ guild settings

    async def settings(self, guild_id: int) -> dict:
        cur = await self.db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "welcome_channel": None,
            "welcome_message": None,
            "goodbye_channel": None,
            "goodbye_message": None,
            "autorole": None,
            "starboard_channel": None,
            "starboard_stars": 3,
            "starboard_emoji": "\u2b50",
            "vouch_channel": None,
            "default_claim_hours": 24,
            "staff_roles": None,
            "legit_channel": None,
            "activity_channel": None,
            "strike_limit": 3,
            "giveaway_cap": None,
        }

    async def set_settings(self, guild_id: int, **fields) -> None:
        allowed = {
            "welcome_channel", "welcome_message", "goodbye_channel", "goodbye_message",
            "autorole", "starboard_channel", "starboard_stars", "starboard_emoji",
            "vouch_channel", "default_claim_hours", "staff_roles", "legit_channel",
            "activity_channel", "strike_limit", "giveaway_cap",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        await self.db.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,)
        )
        assignments = ", ".join(f"{k} = ?" for k in fields)
        await self.db.execute(
            f"UPDATE guild_settings SET {assignments} WHERE guild_id = ?",
            (*fields.values(), guild_id),
        )
        await self.db.commit()

    # ------------------------------------------------------- reaction roles

    async def add_reaction_roles(
        self, guild_id: int, key: str, channel_id: int, message_id: int,
        options: str, title: str | None = None, style: str = "dropdown",
        max_choices: int = 0,
    ) -> bool:
        try:
            await self.db.execute(
                "INSERT INTO reaction_roles (guild_id, key, channel_id, message_id,"
                " options, title, style, max_choices) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (guild_id, key, channel_id, message_id, options, title, style, max_choices),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def reaction_roles(self, guild_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM reaction_roles WHERE guild_id = ? ORDER BY id", (guild_id,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def reaction_role_by_message(self, message_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM reaction_roles WHERE message_id = ?", (message_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_reaction_roles(self, guild_id: int, key: str) -> bool:
        cur = await self.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND key = ?", (guild_id, key)
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ----------------------------------------------------------- starboard

    async def get_star_post(self, source_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM starboard_posts WHERE source_id = ?", (source_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def save_star_post(
        self, source_id: int, guild_id: int, post_id: int, stars: int
    ) -> None:
        await self.db.execute(
            "INSERT INTO starboard_posts (source_id, guild_id, post_id, stars)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET"
            " post_id = excluded.post_id, stars = excluded.stars",
            (source_id, guild_id, post_id, stars),
        )
        await self.db.commit()

    async def delete_star_post(self, source_id: int) -> None:
        await self.db.execute(
            "DELETE FROM starboard_posts WHERE source_id = ?", (source_id,)
        )
        await self.db.commit()

    # ----------------------------------------------------------- reminders

    async def add_reminder(
        self, guild_id: int | None, channel_id: int, user_id: int,
        text: str, remind_at: float,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO reminders (guild_id, channel_id, user_id, text, remind_at,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, user_id, text, remind_at, time.time()),
        )
        await self.db.commit()
        return cur.lastrowid

    async def due_reminders(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM reminders WHERE done = 0 AND remind_at <= ?", (time.time(),)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def user_reminders(self, user_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND done = 0 ORDER BY remind_at",
            (user_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def complete_reminder(self, reminder_id: int) -> None:
        await self.db.execute(
            "UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,)
        )
        await self.db.commit()

    async def cancel_reminder(self, reminder_id: int, user_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE reminders SET done = 1 WHERE id = ? AND user_id = ? AND done = 0",
            (reminder_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------- dashboard aggregates

    async def guild_counts(self, guild_id: int) -> dict:
        """One round trip per metric, used by the dashboard overview."""
        async def scalar(query: str, params: tuple = ()) -> int:
            cur = await self.db.execute(query, params)
            row = await cur.fetchone()
            return row[0] if row else 0

        return {
            "open_tickets": await scalar(
                "SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'open'",
                (guild_id,),
            ),
            "total_tickets": await scalar(
                "SELECT COUNT(*) FROM tickets WHERE guild_id = ?", (guild_id,)
            ),
            "active_giveaways": await scalar(
                "SELECT COUNT(*) FROM giveaways WHERE guild_id = ? AND ended = 0",
                (guild_id,),
            ),
            "pending_applications": await scalar(
                "SELECT COUNT(*) FROM applications WHERE guild_id = ? AND status = 'pending'",
                (guild_id,),
            ),
            "trackers": await scalar(
                "SELECT COUNT(*) FROM trackers WHERE guild_id = ?", (guild_id,)
            ),
            "streams": await scalar(
                "SELECT COUNT(*) FROM stream_subs WHERE guild_id = ?", (guild_id,)
            ),
        }

    # ------------------------------------------------- giveaway winners v2

    async def winners_full(self, giveaway_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM giveaway_winners WHERE giveaway_id = ? ORDER BY id",
            (giveaway_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def winner_row(self, giveaway_id: int, user_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM giveaway_winners WHERE giveaway_id = ? AND user_id = ?"
            " ORDER BY id DESC LIMIT 1",
            (giveaway_id, user_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_winner_choice(
        self, giveaway_id: int, user_id: int, choice: str
    ) -> bool:
        """Only sets a choice once — a second press can't change it."""
        cur = await self.db.execute(
            "UPDATE giveaway_winners SET choice = ? WHERE giveaway_id = ? AND user_id = ?"
            " AND choice IS NULL",
            (choice, giveaway_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def resolve_winner(
        self, giveaway_id: int, user_id: int, payout: str | None
    ) -> None:
        await self.db.execute(
            "UPDATE giveaway_winners SET payout = ?, resolved = 1"
            " WHERE giveaway_id = ? AND user_id = ?",
            (payout, giveaway_id, user_id),
        )
        await self.db.commit()

    async def mark_claimed(
        self, giveaway_id: int, user_id: int, ticket_id: int | None
    ) -> bool:
        cur = await self.db.execute(
            "UPDATE giveaway_winners SET claimed = 1, ticket_id = ?"
            " WHERE giveaway_id = ? AND user_id = ? AND claimed = 0",
            (ticket_id, giveaway_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def expired_claims(self) -> list[dict]:
        """Winners who never pressed Claim within the window."""
        cur = await self.db.execute(
            "SELECT w.*, g.claim_hours, g.prize, g.guild_id, g.channel_id, g.mode"
            " FROM giveaway_winners w JOIN giveaways g ON g.id = w.giveaway_id"
            " WHERE w.claimed = 0 AND w.expired = 0 AND g.claim_hours > 0"
            " AND w.won_at + (g.claim_hours * 3600) <= ?",
            (time.time(),),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def mark_expired(self, giveaway_id: int, user_id: int) -> None:
        await self.db.execute(
            "UPDATE giveaway_winners SET expired = 1 WHERE giveaway_id = ? AND user_id = ?",
            (giveaway_id, user_id),
        )
        await self.db.commit()

    async def unclaimed_giveaways(self) -> list[dict]:
        """Ended giveaways that still have someone who hasn't claimed — used to
        re-register claim buttons after a restart."""
        cur = await self.db.execute(
            "SELECT DISTINCT g.* FROM giveaways g JOIN giveaway_winners w"
            " ON g.id = w.giveaway_id WHERE g.ended = 1 AND w.claimed = 0 AND w.expired = 0"
        )
        return [dict(r) for r in await cur.fetchall()]

    # -------------------------------------------------------------- vouches

    async def add_vouch(
        self,
        guild_id: int,
        from_user: int,
        to_user: int,
        message: str | None,
        source: str = "command",
        giveaway_id: int | None = None,
        message_id: int | None = None,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO vouches (guild_id, from_user, to_user, message, source,"
            " giveaway_id, message_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                from_user,
                to_user,
                message,
                source,
                giveaway_id,
                message_id,
                time.time(),
            ),
        )
        await self.db.commit()
        return cur.lastrowid

    async def vouches_for(self, guild_id: int, user_id: int, limit: int = 25) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM vouches WHERE guild_id = ? AND to_user = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (guild_id, user_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def vouch_count(self, guild_id: int, user_id: int) -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) AS n FROM vouches WHERE guild_id = ? AND to_user = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row["n"] if row else 0

    async def already_vouched(
        self, guild_id: int, from_user: int, to_user: int, within_hours: int = 24
    ) -> bool:
        """Stops the same person vouching the same person repeatedly."""
        cur = await self.db.execute(
            "SELECT 1 FROM vouches WHERE guild_id = ? AND from_user = ? AND to_user = ?"
            " AND created_at > ? LIMIT 1",
            (guild_id, from_user, to_user, time.time() - within_hours * 3600),
        )
        return await cur.fetchone() is not None

    async def vouch_leaderboard(self, guild_id: int, limit: int = 10) -> list[dict]:
        cur = await self.db.execute(
            "SELECT to_user, COUNT(*) AS n FROM vouches WHERE guild_id = ?"
            " GROUP BY to_user ORDER BY n DESC LIMIT ?",
            (guild_id, limit),
        )
        return [{"user_id": r["to_user"], "count": r["n"]} for r in await cur.fetchall()]

    async def delete_vouch(self, guild_id: int, vouch_id: int) -> bool:
        cur = await self.db.execute(
            "DELETE FROM vouches WHERE id = ? AND guild_id = ?", (vouch_id, guild_id)
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------ giveaway edits

    async def update_giveaway(self, giveaway_id: int, **fields) -> bool:
        allowed = {
            "prize", "description", "winner_count", "ends_at", "claim_hours",
            "required_role", "min_account_days", "bonus_role", "bonus_entries",
            "mode", "cancelled", "ended", "value", "parent_id", "double_count",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return False
        assignments = ", ".join(f"{k} = ?" for k in fields)
        cur = await self.db.execute(
            f"UPDATE giveaways SET {assignments} WHERE id = ?",
            (*fields.values(), giveaway_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # --------------------------------------------------------- staff roles

    async def staff_role_ids(self, guild_id: int) -> list[int]:
        settings = await self.settings(guild_id)
        raw = settings.get("staff_roles")
        if not raw:
            return []
        try:
            return [int(r) for r in json.loads(raw)]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []

    async def set_staff_roles(self, guild_id: int, role_ids: list[int]) -> None:
        await self.set_settings(guild_id, staff_roles=json.dumps(sorted(set(role_ids))))

    # -------------------------------------------------------------- strikes

    async def add_strike(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None,
        issued_by: int | None = None,
        check_id: int | None = None,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO strikes (guild_id, user_id, reason, issued_by, check_id,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, reason, issued_by, check_id, time.time()),
        )
        await self.db.commit()
        return cur.lastrowid

    async def strike_count(self, guild_id: int, user_id: int) -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) AS n FROM strikes WHERE guild_id = ? AND user_id = ?"
            " AND active = 1",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return row["n"] if row else 0

    async def strikes_for(self, guild_id: int, user_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM strikes WHERE guild_id = ? AND user_id = ? AND active = 1"
            " ORDER BY created_at DESC",
            (guild_id, user_id),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def clear_strike(self, guild_id: int, strike_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE strikes SET active = 0 WHERE id = ? AND guild_id = ? AND active = 1",
            (strike_id, guild_id),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def clear_all_strikes(self, guild_id: int, user_id: int) -> int:
        cur = await self.db.execute(
            "UPDATE strikes SET active = 0 WHERE guild_id = ? AND user_id = ? AND active = 1",
            (guild_id, user_id),
        )
        await self.db.commit()
        return cur.rowcount

    async def strike_leaderboard(self, guild_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT user_id, COUNT(*) AS n FROM strikes WHERE guild_id = ? AND active = 1"
            " GROUP BY user_id ORDER BY n DESC",
            (guild_id,),
        )
        return [{"user_id": r["user_id"], "count": r["n"]} for r in await cur.fetchall()]

    # ------------------------------------------------------ activity checks

    async def create_activity_check(
        self,
        guild_id: int,
        channel_id: int,
        started_by: int,
        deadline: float,
        strike_on_miss: bool = True,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO activity_checks (guild_id, channel_id, started_by, deadline,"
            " created_at, strike_on_miss) VALUES (?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                channel_id,
                started_by,
                deadline,
                time.time(),
                1 if strike_on_miss else 0,
            ),
        )
        await self.db.commit()
        return cur.lastrowid

    async def set_activity_message(self, check_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE activity_checks SET message_id = ? WHERE id = ?",
            (message_id, check_id),
        )
        await self.db.commit()

    async def get_activity_check(self, check_id: int) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM activity_checks WHERE id = ?", (check_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def record_activity(self, check_id: int, user_id: int) -> bool:
        try:
            await self.db.execute(
                "INSERT INTO activity_responses (check_id, user_id, responded_at)"
                " VALUES (?, ?, ?)",
                (check_id, user_id, time.time()),
            )
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def activity_responders(self, check_id: int) -> list[int]:
        cur = await self.db.execute(
            "SELECT user_id FROM activity_responses WHERE check_id = ?", (check_id,)
        )
        return [r["user_id"] for r in await cur.fetchall()]

    async def due_activity_checks(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM activity_checks WHERE closed = 0 AND deadline <= ?",
            (time.time(),),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def open_activity_checks(self) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM activity_checks WHERE closed = 0")
        return [dict(r) for r in await cur.fetchall()]

    async def close_activity_check(self, check_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE activity_checks SET closed = 1 WHERE id = ? AND closed = 0",
            (check_id,),
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ---------------------------------------------------------- legit votes

    async def create_legit_vote(
        self,
        guild_id: int,
        channel_id: int,
        giveaway_id: int | None,
        subject_id: int | None,
        prize: str | None,
    ) -> int:
        cur = await self.db.execute(
            "INSERT INTO legit_votes (guild_id, channel_id, giveaway_id, subject_id,"
            " prize, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, giveaway_id, subject_id, prize, time.time()),
        )
        await self.db.commit()
        return cur.lastrowid

    async def set_legit_message(self, vote_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE legit_votes SET message_id = ? WHERE id = ?", (message_id, vote_id)
        )
        await self.db.commit()

    async def get_legit_vote(self, vote_id: int) -> dict | None:
        cur = await self.db.execute("SELECT * FROM legit_votes WHERE id = ?", (vote_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def cast_legit_vote(self, vote_id: int, user_id: int, choice: str) -> str:
        """Returns 'new', 'changed' or 'same'. One vote each, changeable."""
        cur = await self.db.execute(
            "SELECT choice FROM legit_vote_entries WHERE vote_id = ? AND user_id = ?",
            (vote_id, user_id),
        )
        row = await cur.fetchone()
        if row is None:
            await self.db.execute(
                "INSERT INTO legit_vote_entries (vote_id, user_id, choice, voted_at)"
                " VALUES (?, ?, ?, ?)",
                (vote_id, user_id, choice, time.time()),
            )
            await self.db.commit()
            return "new"
        if row["choice"] == choice:
            return "same"
        await self.db.execute(
            "UPDATE legit_vote_entries SET choice = ?, voted_at = ?"
            " WHERE vote_id = ? AND user_id = ?",
            (choice, time.time(), vote_id, user_id),
        )
        await self.db.commit()
        return "changed"

    async def legit_tally(self, vote_id: int) -> dict:
        cur = await self.db.execute(
            "SELECT choice, COUNT(*) AS n FROM legit_vote_entries WHERE vote_id = ?"
            " GROUP BY choice",
            (vote_id,),
        )
        counts = {r["choice"]: r["n"] for r in await cur.fetchall()}
        return {
            "legit": counts.get("legit", 0),
            "not_legit": counts.get("not_legit", 0),
        }

    async def legit_voters(self, vote_id: int, choice: str) -> list[int]:
        cur = await self.db.execute(
            "SELECT user_id FROM legit_vote_entries WHERE vote_id = ? AND choice = ?",
            (vote_id, choice),
        )
        return [r["user_id"] for r in await cur.fetchall()]

    async def open_legit_votes(self) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM legit_votes WHERE closed = 0")
        return [dict(r) for r in await cur.fetchall()]

    async def close_legit_vote(self, vote_id: int) -> bool:
        cur = await self.db.execute(
            "UPDATE legit_votes SET closed = 1 WHERE id = ?", (vote_id,)
        )
        await self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------- tickets

    async def set_ticket_ign(self, channel_id: int, ign: str) -> bool:
        cur = await self.db.execute(
            "UPDATE tickets SET ign = ? WHERE channel_id = ?", (ign, channel_id)
        )
        await self.db.commit()
        return cur.rowcount > 0

    # -------------------------------------------------------------- scripts

    async def add_script(
        self,
        guild_id: int,
        name: str,
        code: str,
        created_by: int,
        description: str | None = None,
        staff_only: bool = False,
    ) -> int | None:
        try:
            cur = await self.db.execute(
                "INSERT INTO scripts (guild_id, name, code, description, created_by,"
                " created_at, staff_only) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    name,
                    code,
                    description,
                    created_by,
                    time.time(),
                    1 if staff_only else 0,
                ),
            )
            await self.db.commit()
            return cur.lastrowid
        except aiosqlite.IntegrityError:
            return None

    async def get_script(self, guild_id: int, ref: str | int) -> dict | None:
        """By numeric id or by name, whichever was given."""
        if str(ref).isdigit():
            cur = await self.db.execute(
                "SELECT * FROM scripts WHERE guild_id = ? AND id = ?",
                (guild_id, int(ref)),
            )
            row = await cur.fetchone()
            if row:
                return dict(row)
        cur = await self.db.execute(
            "SELECT * FROM scripts WHERE guild_id = ? AND lower(name) = lower(?)",
            (guild_id, str(ref)),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def scripts(self, guild_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM scripts WHERE guild_id = ? ORDER BY id", (guild_id,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def update_script(self, guild_id: int, ref: str | int, **fields) -> bool:
        allowed = {"name", "code", "description", "enabled", "staff_only"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return False
        script = await self.get_script(guild_id, ref)
        if script is None:
            return False
        fields["updated_at"] = time.time()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        cur = await self.db.execute(
            f"UPDATE scripts SET {assignments} WHERE id = ?",
            (*fields.values(), script["id"]),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def delete_script(self, guild_id: int, ref: str | int) -> bool:
        script = await self.get_script(guild_id, ref)
        if script is None:
            return False
        cur = await self.db.execute("DELETE FROM scripts WHERE id = ?", (script["id"],))
        await self.db.commit()
        return cur.rowcount > 0

    async def bump_script(self, script_id: int) -> None:
        await self.db.execute(
            "UPDATE scripts SET uses = uses + 1 WHERE id = ?", (script_id,)
        )
        await self.db.commit()

    async def all_giveaways(self, guild_id: int) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM giveaways WHERE guild_id = ? ORDER BY created_at DESC",
            (guild_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def all_winners(self, guild_id: int) -> list[dict]:
        """Winners joined to their giveaway, newest first — for /getdata."""
        cur = await self.db.execute(
            "SELECT w.*, g.prize, g.guild_id FROM giveaway_winners w"
            " JOIN giveaways g ON g.id = w.giveaway_id WHERE g.guild_id = ?"
            " ORDER BY w.won_at DESC",
            (guild_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
