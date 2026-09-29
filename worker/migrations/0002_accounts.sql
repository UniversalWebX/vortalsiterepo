-- Vortal accounts (used by Volatile for online play), sessions, join tickets,
-- bans and the moderation log.
CREATE TABLE IF NOT EXISTS accounts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL,                 -- as the player typed it
  username_key  TEXT NOT NULL UNIQUE,          -- lowercase, for lookups and uniqueness
  pass_hash     TEXT NOT NULL,                 -- PBKDF2-SHA256, hex
  pass_salt     TEXT NOT NULL,                 -- hex
  pass_iter     INTEGER NOT NULL,
  role          TEXT NOT NULL DEFAULT 'player', -- 'player' or 'mod'
  created_at    INTEGER NOT NULL,              -- milliseconds since 1970
  banned_at     INTEGER,                       -- set while banned
  ban_until     INTEGER,                       -- null = permanent
  ban_reason    TEXT,
  banned_by     TEXT
);

-- Signed-in devices. Only a hash of each token is stored.
CREATE TABLE IF NOT EXISTS sessions (
  token_hash  TEXT PRIMARY KEY,
  account_id  INTEGER NOT NULL,
  created_at  INTEGER NOT NULL,
  last_used   INTEGER NOT NULL,
  label       TEXT                             -- e.g. "Volatile on Windows"
);
CREATE INDEX IF NOT EXISTS sessions_account ON sessions (account_id);

-- Short-lived, single-use join tickets a player hands to a game host.
CREATE TABLE IF NOT EXISTS tickets (
  ticket_hash  TEXT PRIMARY KEY,
  account_id   INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL
);

-- Failed sign-ins and sign-ups, for rate limiting (hashed visitor + name).
CREATE TABLE IF NOT EXISTS account_fails (
  key  TEXT NOT NULL,
  at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS account_fails_key ON account_fails (key, at);

-- What moderators did.
CREATE TABLE IF NOT EXISTS mod_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  at         INTEGER NOT NULL,
  moderator  TEXT NOT NULL,
  action     TEXT NOT NULL,                    -- 'ban', 'unban', 'kick', 'mute', 'report'…
  target     TEXT,
  reason     TEXT
);
CREATE INDEX IF NOT EXISTS mod_log_at ON mod_log (at DESC);
