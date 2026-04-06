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

CREATE TABLE IF NOT EXISTS run_relationships (
  parent_run_id TEXT NOT NULL,
  child_run_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (parent_run_id, child_run_id),
  FOREIGN KEY (parent_run_id) REFERENCES task_runs (run_id),
  FOREIGN KEY (child_run_id) REFERENCES task_runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_relationships_parent
  ON run_relationships (parent_run_id, created_at);

CREATE INDEX IF NOT EXISTS idx_run_relationships_child
  ON run_relationships (child_run_id);

CREATE TABLE IF NOT EXISTS run_checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_id
  ON run_checkpoints (run_id, created_at);

CREATE TABLE IF NOT EXISTS run_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  artifact_name TEXT NOT NULL,
  path TEXT,
  external_url TEXT,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_artifacts_run_id
  ON run_artifacts (run_id, created_at);

CREATE TABLE IF NOT EXISTS run_skill_selections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  parent_run_id TEXT,
  run_kind TEXT NOT NULL,
  agent_role TEXT NOT NULL,
  registry_version TEXT,
  selection_key TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs (run_id),
  FOREIGN KEY (parent_run_id) REFERENCES task_runs (run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_skill_selections_run_id
  ON run_skill_selections (run_id, created_at);

CREATE INDEX IF NOT EXISTS idx_run_skill_selections_parent_run_id
  ON run_skill_selections (parent_run_id, created_at);

CREATE TABLE IF NOT EXISTS thread_links (
  chat_thread_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  provider_type TEXT NOT NULL,
  linked_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES task_runs (run_id)
);
