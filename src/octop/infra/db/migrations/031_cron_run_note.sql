-- Schema v31: cron run notes, used to record degraded deliveries (for example a
-- text reminder that was pushed without writing session history because no model
-- is configured).
-- SQLite applies this through migrate.py so a database that already has the
-- column still advances its version watermark.

ALTER TABLE cron_runs ADD COLUMN note TEXT;

UPDATE _schema_version SET version = 31;
