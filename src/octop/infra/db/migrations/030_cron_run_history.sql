-- Schema v30: cron run history and explicit scheduling semantics.
-- SQLite applies this through migrate.py::_ensure_cron_run_schema so the
-- upgrade stays idempotent for databases whose version watermark skipped it.

CREATE TABLE IF NOT EXISTS cron_runs (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id          TEXT NOT NULL UNIQUE,
  cron_id         TEXT NOT NULL REFERENCES cron_jobs(cron_id) ON DELETE CASCADE,
  trigger_kind    TEXT NOT NULL DEFAULT 'schedule',
  scheduled_for   INTEGER,
  status          TEXT NOT NULL DEFAULT 'running',
  attempt         INTEGER NOT NULL DEFAULT 1,
  started_at      INTEGER NOT NULL,
  finished_at     INTEGER,
  duration_ms     INTEGER,
  error           TEXT,
  created_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cron_runs_job_started
  ON cron_runs (cron_id, started_at DESC);

-- One record per planned fire time: a restart or a duplicate scheduler tick
-- cannot enqueue the same slot twice.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cron_runs_slot
  ON cron_runs (cron_id, scheduled_for)
  WHERE scheduled_for IS NOT NULL;

ALTER TABLE cron_jobs ADD COLUMN timezone TEXT NOT NULL DEFAULT '';
ALTER TABLE cron_jobs ADD COLUMN next_run_at INTEGER;
ALTER TABLE cron_jobs ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cron_jobs ADD COLUMN retry_backoff_seconds INTEGER NOT NULL DEFAULT 60;
ALTER TABLE cron_jobs ADD COLUMN catch_up_misses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cron_jobs ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0;

UPDATE _schema_version SET version = 30;
