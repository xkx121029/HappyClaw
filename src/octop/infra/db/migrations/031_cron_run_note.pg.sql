-- Schema v31: cron run notes, used to record degraded deliveries (for example a
-- text reminder that was pushed without writing session history because no model
-- is configured).
ALTER TABLE cron_runs ADD COLUMN IF NOT EXISTS note TEXT;

UPDATE _schema_version SET version = 31;
