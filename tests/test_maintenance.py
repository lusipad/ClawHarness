from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness_runtime.config import (
    ExecutorRuntimeConfig,
    HarnessRuntimeConfig,
    OpenClawHooksConfig,
    RocketChatRuntimeConfig,
    RuntimeStorageConfig,
)
from harness_runtime.maintenance import RunMaintenanceService
from run_store import RunStore, TaskRun


class MaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.workspaces = self.base / "workspaces"
        self.workspaces.mkdir()
        self.store = RunStore(self.base / "harness.db")
        self.store.initialize()
        self.config = HarnessRuntimeConfig(
            azure_devops=None,
            github=None,
            rocketchat=RocketChatRuntimeConfig(mode="rocketchat-webhook", webhook_url=None, channel=None),
            executor=ExecutorRuntimeConfig(mode="codex-cli", harness="codex", backend="cli", timeout_seconds=60),
            runtime=RuntimeStorageConfig(
                sqlite_path=str(self.base / "harness.db"),
                workspace_root=str(self.workspaces),
                branch_prefix="ai",
                lock_ttl_seconds=1800,
                dedupe_ttl_seconds=86400,
                audit_retention_days=30,
                terminal_run_retention_days=5,
                cleanup_batch_size=20,
            ),
            openclaw_hooks=OpenClawHooksConfig(
                base_url="http://127.0.0.1:18789",
                token="secret",
                path="/hooks",
                agent_id="main",
                default_session_key="hook:harness",
                wake_mode="now",
            ),
            openclaw_gateway_token=None,
            ingress_token=None,
            readonly_token=None,
            owner="maintenance-test",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_run(self, *, run_id: str, status: str, updated_at: str, workspace_path: str) -> TaskRun:
        return self.store.create_run(
            TaskRun(
                run_id=run_id,
                provider_type="azure-devops",
                task_id=run_id,
                task_key=f"TASK#{run_id}",
                repo_id="repo-1",
                workspace_path=workspace_path,
                session_id=f"session-{run_id}",
                executor_type="codex-cli",
                status=status,
                started_at=updated_at,
                updated_at=updated_at,
            )
        )

    def test_cleanup_terminal_runs_deletes_old_workspace_inside_root(self) -> None:
        workspace = self.workspaces / "run-old"
        workspace.mkdir()
        (workspace / "README.md").write_text("hello\n", encoding="utf-8")
        self._create_run(
            run_id="run-old",
            status="completed",
            updated_at="2026-04-01T12:00:00Z",
            workspace_path=str(workspace),
        )
        service = RunMaintenanceService(config=self.config, store=self.store)

        result = service.cleanup_terminal_runs(now="2026-04-06T12:00:00Z")

        self.assertEqual(1, result.cleaned_runs)
        self.assertEqual(1, result.deleted_workspaces)
        self.assertFalse(workspace.exists())
        audit = self.store.list_audit("run-old")
        self.assertEqual("maintenance_cleanup_completed", audit[0]["event_type"])

    def test_cleanup_terminal_runs_skips_workspace_still_used_by_active_run(self) -> None:
        workspace = self.workspaces / "run-shared"
        workspace.mkdir()
        self._create_run(
            run_id="run-old",
            status="completed",
            updated_at="2026-04-01T12:00:00Z",
            workspace_path=str(workspace),
        )
        self._create_run(
            run_id="run-live",
            status="coding",
            updated_at="2026-04-06T12:00:00Z",
            workspace_path=str(workspace),
        )
        service = RunMaintenanceService(config=self.config, store=self.store)

        result = service.cleanup_terminal_runs(now="2026-04-06T12:00:00Z")

        self.assertEqual(0, result.deleted_workspaces)
        self.assertTrue(workspace.exists())
        self.assertEqual("workspace_in_use", result.run_results[0]["reason"])
        audit = self.store.list_audit("run-old")
        self.assertEqual("maintenance_cleanup_skipped", audit[0]["event_type"])


if __name__ == "__main__":
    unittest.main()
