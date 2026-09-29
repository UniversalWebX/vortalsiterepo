-- The public Volatile server list. Servers check in every minute; ones that
-- stop checking in drop off the list after 3 minutes.
CREATE TABLE IF NOT EXISTS servers (
  address     TEXT PRIMARY KEY,     -- "ip:port" as seen by vortal.space
  ip_hash     TEXT NOT NULL,        -- for the per-address limit
  name        TEXT NOT NULL,
  world       TEXT,
  players     INTEGER NOT NULL DEFAULT 0,
  max_players INTEGER NOT NULL DEFAULT 8,
  version     TEXT,
  build       INTEGER,
  protocol    INTEGER,
  dedicated   INTEGER NOT NULL DEFAULT 0,
  platform    TEXT,
  last_seen   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS servers_seen ON servers (last_seen DESC);
CREATE INDEX IF NOT EXISTS servers_ip ON servers (ip_hash);
