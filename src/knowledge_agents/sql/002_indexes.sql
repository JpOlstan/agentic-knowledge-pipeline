CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_lease_expires_at ON runs(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_attempts_run_id_operation ON attempts(run_id, operation);
CREATE INDEX IF NOT EXISTS idx_repair_tasks_status_next_attempt ON repair_tasks(status, next_attempt_at);
