-- Schema v27: persisted Bao dispatch tasks.

CREATE TABLE IF NOT EXISTS bao_tasks (
  id                  TEXT PRIMARY KEY,
  user_id             INTEGER NOT NULL,
  agent_id            TEXT NOT NULL,
  agent_name          TEXT NOT NULL DEFAULT '',
  thread_id           TEXT NOT NULL,
  session_title       TEXT NOT NULL DEFAULT '',
  project_key         TEXT NOT NULL DEFAULT '',
  project_name        TEXT NOT NULL DEFAULT '',
  task_text           TEXT NOT NULL,
  source              TEXT NOT NULL DEFAULT 'bao',
  route_reason_json   TEXT NOT NULL DEFAULT '{}',
  status              TEXT NOT NULL,
  result_text         TEXT,
  error_text          TEXT,
  created_at          INTEGER NOT NULL,
  dispatched_at       INTEGER NOT NULL,
  updated_at          INTEGER NOT NULL,
  completed_at        INTEGER,
  acknowledged_at     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_bao_tasks_user_dispatched
  ON bao_tasks (user_id, dispatched_at DESC);

CREATE INDEX IF NOT EXISTS idx_bao_tasks_thread_status
  ON bao_tasks (thread_id, status);

UPDATE _schema_version SET version = 27;
