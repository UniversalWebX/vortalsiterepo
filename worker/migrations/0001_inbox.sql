-- The vortal.space inbox: contact-form messages and routed email.
CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  INTEGER NOT NULL,              -- milliseconds since 1970
  source      TEXT NOT NULL,                 -- 'form' or 'email'
  name        TEXT,
  email       TEXT,
  topic       TEXT,
  subject     TEXT,
  body        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'new',   -- 'new', 'read', 'archived'
  ip_hash     TEXT,                          -- for rate limiting only; never the IP itself
  country     TEXT,
  user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS messages_created ON messages (created_at DESC);
CREATE INDEX IF NOT EXISTS messages_visitor ON messages (ip_hash, created_at);

-- Wrong panel keys, so repeated guessing gets locked out for 15 minutes.
CREATE TABLE IF NOT EXISTS admin_fails (
  ip_hash  TEXT NOT NULL,
  at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS admin_fails_visitor ON admin_fails (ip_hash, at);
