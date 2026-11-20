-- Schema v28: Bao conversation memory, follow-up state and proactive push log.

CREATE TABLE IF NOT EXISTS bao_messages (
  id          TEXT PRIMARY KEY,
  user_id     INTEGER NOT NULL,
  role        TEXT NOT NULL,
  text        TEXT NOT NULL,
  intent      TEXT NOT NULL DEFAULT '',
  refs_json   TEXT NOT NULL DEFAULT '{}',
  task_id     TEXT,
  created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bao_messages_user_created
  ON bao_messages (user_id, created_at DESC);

ALTER TABLE bao_tasks ADD COLUMN followup_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE bao_tasks ADD COLUMN last_followup_at INTEGER;

ALTER TABLE bao_tasks ADD COLUMN eval_status TEXT;

ALTER TABLE bao_tasks ADD COLUMN eval_at INTEGER;

CREATE TABLE IF NOT EXISTS bao_proactive_log (
  id                TEXT PRIMARY KEY,
  user_id           INTEGER NOT NULL,
  task_id           TEXT NOT NULL,
  kind              TEXT NOT NULL,
  dedupe_key        TEXT NOT NULL,
  delivered         INTEGER NOT NULL DEFAULT 0,
  suppressed_reason TEXT,
  created_at        INTEGER NOT NULL
);

-- Only a delivered notification consumes the dedupe key; a muted or
-- rate-limited attempt must not permanently shadow a later real delivery.
CREATE UNIQUE INDEX IF NOT EXISTS idx_bao_proactive_dedupe
  ON bao_proactive_log (dedupe_key) WHERE delivered = 1;

CREATE INDEX IF NOT EXISTS idx_bao_proactive_user_created
  ON bao_proactive_log (user_id, created_at DESC);

UPDATE _schema_version SET version = 28;
