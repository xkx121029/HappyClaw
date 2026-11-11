-- Schema v26: single-user local owner marker.
-- Additive only: no user rows are deleted, no columns are rewritten.
-- `local_owner` records which legacy account (if any) is treated as the one
-- local user; older accounts stay in `users` untouched.

CREATE TABLE IF NOT EXISTS local_owner (
  user_id    BIGINT PRIMARY KEY,
  adopted_at BIGINT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'migration'
);

-- Prefer the lowest-id active administrator.
INSERT INTO local_owner(user_id, adopted_at, source)
SELECT id, EXTRACT(EPOCH FROM now())::bigint, 'migration-admin'
FROM users
WHERE role = 'admin'
  AND NOT EXISTS (SELECT 1 FROM local_owner)
ORDER BY id
LIMIT 1;

-- Otherwise adopt the lowest-id account of any role.
INSERT INTO local_owner(user_id, adopted_at, source)
SELECT id, EXTRACT(EPOCH FROM now())::bigint, 'migration'
FROM users
WHERE NOT EXISTS (SELECT 1 FROM local_owner)
ORDER BY id
LIMIT 1;

UPDATE _schema_version SET version = 26;
