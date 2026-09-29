-- vortal.space community: the launch chat and announcements (worker/community.js).

-- Chat messages. Deleted ones keep their row (deleted_at) so every open page
-- can take them down on its next poll.
CREATE TABLE IF NOT EXISTS chat_messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          INTEGER NOT NULL,                -- milliseconds since 1970
  account_id  INTEGER NOT NULL,
  username    TEXT NOT NULL,
  role        TEXT NOT NULL DEFAULT 'player',
  body        TEXT NOT NULL,
  deleted_at  INTEGER,
  deleted_by  TEXT
);
CREATE INDEX IF NOT EXISTS chat_messages_account ON chat_messages (account_id, at);
CREATE INDEX IF NOT EXISTS chat_messages_deleted ON chat_messages (deleted_at);

-- Accounts muted in the chat (they can still play online; a ban stops both).
CREATE TABLE IF NOT EXISTS chat_mutes (
  account_id  INTEGER PRIMARY KEY,
  until       INTEGER,                         -- null = until unmuted
  reason      TEXT,
  muted_by    TEXT
);

-- Announcements, shown from `at` on (so one can be scheduled).
CREATE TABLE IF NOT EXISTS announcements (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at          INTEGER NOT NULL,
  author      TEXT NOT NULL,
  title       TEXT NOT NULL,
  body        TEXT NOT NULL DEFAULT '',
  link        TEXT NOT NULL DEFAULT '',
  pinned      INTEGER NOT NULL DEFAULT 0,
  deleted_at  INTEGER
);
CREATE INDEX IF NOT EXISTS announcements_at ON announcements (at DESC);

-- The launch announcement, scheduled for October 1, 5:30 PM Pacific.
INSERT INTO announcements (at, author, title, body, link, pinned)
SELECT 1790901000000, 'Vortal', 'Volatile 1.0 is out now',
  'The official release is here: easier automation, Vortal accounts, public servers and fair play. Download it free for Windows, Mac and Android, then come say hi in the chat.',
  '/volatile', 1
WHERE NOT EXISTS (SELECT 1 FROM announcements WHERE at = 1790901000000 AND author = 'Vortal');
