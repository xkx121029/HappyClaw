-- Schema v29: projects own workspaces; threads remember their project or session directory.

CREATE TABLE IF NOT EXISTS projects (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  TEXT NOT NULL UNIQUE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  root_dir    TEXT,
  is_default  INTEGER NOT NULL DEFAULT 0,
  origin      TEXT NOT NULL DEFAULT 'manual',
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

-- One default project per owner; partial unique index keeps it unique without
-- blocking any number of regular projects.
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_default_per_user
  ON projects (user_id) WHERE is_default = 1;

CREATE INDEX IF NOT EXISTS idx_projects_user_updated
  ON projects (user_id, updated_at DESC);

-- threads.project_id / workspace_kind / workspace_dir are added by
-- _ensure_projects_schema() in migrate.py: SQLite has no
-- ADD COLUMN IF NOT EXISTS, so replaying this file must not ALTER again.

UPDATE _schema_version SET version = 29;
