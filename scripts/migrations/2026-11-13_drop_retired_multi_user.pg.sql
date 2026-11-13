-- Manual cleanup script: DROP retired multi-user tables (PostgreSQL).
--
-- STATUS: NOT executed, NOT verified against a real database. Only the SQL
-- syntax was reviewed. Treat it as a reviewed draft for a future cleanup.
--
-- NOT auto-applied. This file deliberately lives outside
-- src/octop/infra/db/migrations/, so the migration runner never picks it up.
--
-- BACKUP IS MANDATORY before running. Stop Octop first, then:
--   pg_dump --format=custom --file=octop-20261113.dump $env:OCTOP_DATABASE_URL
--
-- MANDATORY CODE CHANGE, NOT OPTIONAL: running this script requires removing
-- the matching CREATE/backfill code in src/octop/infra/db/migrate.py in the
-- same change, otherwise the next boot recreates these tables empty and the
-- DROP accomplishes nothing:
--   user_invites        -> _ensure_user_invites_schema()
--   sso_login_states    -> _ensure_sso_schema() (CREATE + indexes)
--   user_sso_identities -> _ensure_user_sso_identities_schema() (incl. backfill)
--   auth_challenges     -> version-25 ensure block
-- See 2026-11-12/single-user-cleanup/outputs/multi-user-residue.md §13.
--
-- Run with psql:
--   psql "$OCTOP_DATABASE_URL" -f 2026-11-13_drop_retired_multi_user.pg.sql
--
-- Idempotent: IF EXISTS makes a second run a no-op.

BEGIN;

DROP TABLE IF EXISTS user_invites;
DROP TABLE IF EXISTS sso_login_states;
DROP TABLE IF EXISTS user_sso_identities;
DROP TABLE IF EXISTS auth_challenges;

COMMIT;
