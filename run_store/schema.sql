-- ClawHarness MVP runtime schema.
-- SQLite is the only runtime store for v1.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS task_runs (
  run_id TEXT PRIMARY KEY,
  provider_type TEXT NOT NULL,
  task_id TEXT NOT NULL,
  task_key TEXT NOT NULL,
  repo_id TEXT,
  branch_name TEXT,
  workspace_path TEXT,
  pr_id TEXT,
  ci_run_id TEXT,
  chat_thread_id TEXT,
  session_id TEXT NOT NULL,
  executor_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN (
      'queued',
      'claimed',
      'planning',
      'coding',
      'opening_pr',
      'awaiting_ci',
      'awaiting_review',
      'awaiting_human',
      'completed',
      'failed',
      'cancelled'
    )
  ),
  retry_count INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_runs_task_key
  ON task_runs (task_key);

CREATE INDEX IF NOT EXISTS idx_task_runs_status
  ON task_runs (status);

CREATE INDEX IF NOT EXISTS idx_task_runs_pr_id
  ON task_runs (pr_id);

CREATE INDEX IF NOT EXISTS idx_task_runs_ci_run_id
  ON task_runs (ci_run_id);

CREATE TABLE IF NOT EXISTS task_locks (
  lock_key TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  owner TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_task_locks_expires_at
  ON task_locks (expires_at);

CREATE TABLE IF NOT EXISTS event_dedupe (
  fingerprint TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_id TEXT,
  received_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_dedupe_expires_at
  ON event_dedupe (expires_at);

CREATE TABLE IF NOT EXISTS run_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_audit_run_id
  ON run_audit (run_id, created_at);

CREATE TABLE IF NOT EXISTS thread_links (
  chat_thread_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  provider_type TEXT NOT NULL,
  linked_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs (run_id)
);
