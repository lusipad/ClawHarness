from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ado_client import CommitPushResult, RepositoryInfo, WorkspacePreparationResult
from codex_acp_runner import AcpSpawnResult, ExecutorResult, ExecutorRunOutcome
from harness_runtime.config import (
    AzureDevOpsRuntimeConfig,
    ExecutorRuntimeConfig,
    HarnessRuntimeConfig,
    OpenClawHooksConfig,
    RocketChatRuntimeConfig,
    RuntimeStorageConfig,
)
from harness_runtime.orchestrator import TaskRunOrchestrator
from run_store import RunStore, TaskRun


class RecordingShellRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses: list[tuple[int, str, str]] = []

    def queue(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((returncode, stdout, stderr))

    def __call__(self, command: list[str], cwd: str | Path | None, env: dict[str, str] | None):
        self.calls.append({"command": command, "cwd": str(cwd) if cwd is not None else None, "env": env})
        if not self.responses:
            raise AssertionError("No queued shell response")
        returncode, stdout, stderr = self.responses.pop(0)
        return type(
            "Completed",
            (),
            {"returncode": returncode, "stdout": stdout, "stderr": stderr},
        )()


class FakeExecutorRunner:
    def __init__(self, result: ExecutorResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def run_and_wait(self, request, *, result_path, timeout_seconds, poll_interval_seconds):
        self.calls.append(
            {
                "request": request,
                "result_path": str(result_path),
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
            }
        )
        return ExecutorRunOutcome(
            spawn=AcpSpawnResult(
                accepted=True,
                child_session_key="agent:main:task",
                session_id="session-1",
            ),
            result=self.result,
        )


class FakeAdoClient:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.calls: list[tuple[str, object]] = []

    def prepare_workspace(self, repository_id: str, *, workspace_root: str | Path, run_id: str) -> WorkspacePreparationResult:
        self.calls.append(("prepare_workspace", repository_id))
        return WorkspacePreparationResult(
            repository=RepositoryInfo(
                repository_id=repository_id,
                name="AI-Review-Test",
                default_branch="refs/heads/main",
                remote_url="https://dev.azure.com/example/ExampleProject/_git/AI-Review-Test",
            ),
            workspace_path=str(self.workspace_path),
            base_branch="refs/heads/main",
        )

    def create_branch(self, workspace_path: str | Path, *, branch_name: str, base_branch: str) -> str:
        self.calls.append(("create_branch", branch_name))
        return f"refs/heads/{branch_name}"

    def commit_and_push(self, workspace_path: str | Path, *, branch_name: str, commit_message: str) -> CommitPushResult:
        self.calls.append(("commit_and_push", branch_name))
        return CommitPushResult(
            branch_name=branch_name,
            commit_sha="abc123",
            remote_ref=branch_name,
            created_commit=True,
        )

    def create_pull_request(
        self,
        repository_id: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers=None,
        supports_iterations=None,
    ) -> dict[str, object]:
        self.calls.append(("create_pull_request", source_branch))
        return {"pullRequestId": 42}

    def add_task_comment(self, work_item_id: int | str, text: str) -> dict[str, object]:
        self.calls.append(("add_task_comment", str(work_item_id)))
        return {"id": 1}

    def get_task(self, work_item_id: int | str, *, fields=None, expand=None, as_of=None) -> dict[str, object]:
        self.calls.append(
            (
                "get_task",
                {
                    "work_item_id": str(work_item_id),
                    "fields": list(fields) if fields is not None else None,
                    "expand": expand,
                    "as_of": as_of,
                },
            )
        )
        return {
            "id": int(work_item_id),
            "fields": {
                "System.TeamProject": "AI-Review-Test",
                "System.Title": "Update the README",
                "System.Description": "Add V1 validation note",
            },
        }


class TaskRunOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        (self.workspace / "README.md").write_text("hello\n", encoding="utf-8")

        self.config = HarnessRuntimeConfig(
            azure_devops=AzureDevOpsRuntimeConfig(
                base_url="https://dev.azure.com/example",
                project="ExampleProject",
                mode="ado-rest",
                pat="secret",
                webhook_secret=None,
            ),
            rocketchat=RocketChatRuntimeConfig(
                mode="rocketchat-webhook",
                webhook_url=None,
                channel=None,
            ),
            executor=ExecutorRuntimeConfig(
                mode="codex-acp",
                harness="codex",
                backend="acpx",
                timeout_seconds=60,
            ),
            runtime=RuntimeStorageConfig(
                sqlite_path=str(self.base / "harness.db"),
                workspace_root=str(self.base / "workspaces"),
                branch_prefix="ai",
                lock_ttl_seconds=1800,
                dedupe_ttl_seconds=86400,
                audit_retention_days=30,
            ),
            openclaw_hooks=OpenClawHooksConfig(
                base_url="http://127.0.0.1:18789",
                token="secret",
                path="/hooks",
                agent_id="main",
                default_session_key="hook:harness",
                wake_mode="now",
            ),
            openclaw_gateway_token="gateway-secret",
            ingress_token=None,
            owner="test-owner",
        )
        self.store = RunStore(self.config.runtime.sqlite_path)
        self.store.initialize()
        self.task_context = {
            "id": 123,
            "fields": {
                "System.TeamProject": "AI-Review-Test",
                "System.Title": "Update the README",
                "System.Description": "Add V1 validation note",
            },
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create_run(self, *, status: str = "claimed") -> TaskRun:
        return self.store.create_run(
            TaskRun(
                run_id="run-1",
                provider_type="azure-devops",
                task_id="123",
                task_key="AI-Review-Test#123",
                repo_id="repo-1",
                session_id="manual:ai-review-test-123",
                executor_type="codex-acp",
                status=status,
            )
        )

    def test_run_claimed_task_pushes_branch_and_opens_pr(self) -> None:
        self.create_run()
        shell_runner = RecordingShellRunner()
        shell_runner.queue()
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            ExecutorResult(
                status="completed",
                summary="Updated the README with validation notes.",
                changed_files=["README.md"],
                checks=[],
                follow_up=["wait for review"],
            )
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=ado_client,
            executor_runner=executor_runner,
            shell_runner=shell_runner,
        )

        run = orchestrator.run_claimed_task("run-1", task_context=self.task_context)

        self.assertEqual("awaiting_review", run.status)
        self.assertEqual("42", run.pr_id)
        self.assertTrue(run.branch_name.startswith("refs/heads/ai/123"))
        result_path = Path(executor_runner.calls[0]["result_path"])
        self.assertTrue(result_path.is_absolute())
        self.assertNotIn(self.workspace, result_path.parents)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("workspace_prepared", audit_events)
        self.assertIn("executor_completed", audit_events)
        self.assertIn("checks_completed", audit_events)
        self.assertIn(("create_pull_request", run.branch_name), ado_client.calls)

    def test_run_claimed_task_blocks_when_checks_fail(self) -> None:
        self.create_run()
        shell_runner = RecordingShellRunner()
        shell_runner.queue(returncode=1, stderr="trailing whitespace")
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            ExecutorResult(
                status="completed",
                summary="Updated the README with invalid formatting.",
                changed_files=["README.md"],
                checks=[],
                follow_up=[],
            )
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=ado_client,
            executor_runner=executor_runner,
            shell_runner=shell_runner,
        )

        run = orchestrator.run_claimed_task("run-1", task_context=self.task_context)

        self.assertEqual("awaiting_human", run.status)
        self.assertIsNone(run.pr_id)
        self.assertNotIn(("create_pull_request", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        blocked_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("run_blocked", blocked_events)

    def test_claim_manual_task_loads_task_without_expand_when_fields_are_requested(self) -> None:
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            ExecutorResult(
                status="completed",
                summary="unused",
                changed_files=[],
                checks=[],
                follow_up=[],
            )
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=ado_client,
            executor_runner=executor_runner,
        )

        run, context = orchestrator.claim_manual_task(task_id="123", repo_id="repo-1")

        self.assertEqual("manual-ai-review-test-123", run.run_id)
        self.assertEqual("AI-Review-Test", context["fields"]["System.TeamProject"])
        self.assertIn(
            (
                "get_task",
                {
                    "work_item_id": "123",
                    "fields": [
                        "System.Title",
                        "System.Description",
                        "System.State",
                        "System.TeamProject",
                        "System.AssignedTo",
                    ],
                    "expand": None,
                    "as_of": None,
                },
            ),
            ado_client.calls,
        )


if __name__ == "__main__":
    unittest.main()
