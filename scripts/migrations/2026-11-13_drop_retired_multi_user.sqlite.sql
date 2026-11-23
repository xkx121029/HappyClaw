-- Manual cleanup script: DROP retired multi-user tables (SQLite).
--
-- STATUS: NOT executed, NOT verified against a real database. Only the SQL
-- syntax was reviewed. Treat it as a reviewed draft for a future cleanup.
--
-- NOT auto-applied. This file deliberately lives outside
-- src/happyclaw/infra/db/migrations/, so the migration runner never picks it up.
--
-- BACKUP IS MANDATORY before running. Stop Octop first, then copy the database
-- together with its WAL/SHM files (a plain copy of octop.db alone can miss
-- committed data):
--   $db = "$env:USERPROFILE\.octop\octop.db"
--   Copy-Item $db "$db.bak-20261113" -Force
--   Copy-Item "$db-wal" "$db.bak-20261113-wal" -Force -ErrorAction SilentlyContinue
--   Copy-Item "$db-shm" "$db.bak-20261113-shm" -Force -ErrorAction SilentlyContinue
--   # or, preferred, an online consistent backup:
--   # sqlite3 $db ".backup '$db.bak-20261113'"
--
-- MANDATORY CODE CHANGE, NOT OPTIONAL: running this script requires removing
-- the matching CREATE/backfill code in src/happyclaw/infra/db/migrate.py in the
-- same change, otherwise the next boot recreates these tables empty and the
-- DROP accomplishes nothing:
--   user_invites        -> _ensure_user_invites_schema()
--   sso_login_states    -> _ensure_sso_schema() (CREATE + indexes)
--   user_sso_identities -> _ensure_user_sso_identities_schema() (incl. backfill)
--   auth_challenges     -> version-25 ensure block
-- See 2026-11-12/single-user-cleanup/outputs/multi-user-residue.md §13.
--
-- Run with the sqlite3 CLI:
--   sqlite3 "%USERPROFILE%\.octop\octop.db" < 2026-11-13_drop_retired_multi_user.sqlite.sql
--
-- Idempotent: IF EXISTS makes a second run a no-op.

BEGIN IMMEDIATE;

DROP TABLE IF EXISTS user_invites;
DROP TABLE IF EXISTS sso_login_states;
DROP TABLE IF EXISTS user_sso_identities;
DROP TABLE IF EXISTS auth_challenges;

COMMIT;
