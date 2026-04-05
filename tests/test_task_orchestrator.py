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
    def __init__(self, result: ExecutorResult, *, session_id: str = "session-1") -> None:
        self.result = result
        self.session_id = session_id
        self.calls: list[dict[str, object]] = []

    def run_and_wait(self, request, *, result_path, timeout_seconds, poll_interval_seconds, resume_session_id=None):
        self.calls.append(
            {
                "request": request,
                "result_path": str(result_path),
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
                "resume_session_id": resume_session_id,
            }
        )
        return ExecutorRunOutcome(
            spawn=AcpSpawnResult(
                accepted=True,
                child_session_key="agent:main:task",
                session_id=self.session_id,
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

    def reply_to_pull_request(
        self,
        repository_id: str,
        pull_request_id: int | str,
        *,
        thread_id: int | str,
        content: str,
        parent_comment_id: int = 0,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "reply_to_pull_request",
                {
                    "repository_id": repository_id,
                    "pull_request_id": str(pull_request_id),
                    "thread_id": str(thread_id),
                    "content": content,
                    "parent_comment_id": parent_comment_id,
                },
            )
        )
        return {"id": 7}

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

    def retry_build(self, build_id: int | str) -> dict[str, object]:
        self.calls.append(("retry_build", str(build_id)))
        return {"id": 101, "status": "notStarted"}


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

    def create_run(
        self,
        *,
        status: str = "claimed",
        pr_id: str | None = None,
        ci_run_id: str | None = None,
        branch_name: str | None = None,
        workspace_path: str | None = None,
        session_id: str = "manual:ai-review-test-123",
    ) -> TaskRun:
        return self.store.create_run(
            TaskRun(
                run_id="run-1",
                provider_type="azure-devops",
                task_id="123",
                task_key="AI-Review-Test#123",
                repo_id="repo-1",
                pr_id=pr_id,
                ci_run_id=ci_run_id,
                branch_name=branch_name,
                workspace_path=workspace_path,
                session_id=session_id,
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
        self.assertEqual("session-1", run.session_id)
        self.assertTrue(run.branch_name.startswith("refs/heads/ai/123"))
        result_path = Path(executor_runner.calls[0]["result_path"])
        self.assertTrue(result_path.is_absolute())
        self.assertNotIn(self.workspace, result_path.parents)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("workspace_prepared", audit_events)
        self.assertIn("executor_completed", audit_events)
        self.assertIn("executor_session_updated", audit_events)
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

    def test_resume_from_pr_feedback_reuses_session_and_replies_without_new_run(self) -> None:
        self.create_run(
            status="awaiting_review",
            pr_id="42",
            branch_name="refs/heads/ai/123-update-the-readme",
            workspace_path=str(self.workspace),
            session_id="session-existing",
        )
        shell_runner = RecordingShellRunner()
        shell_runner.queue()
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            ExecutorResult(
                status="completed",
                summary="Addressed the requested README update.",
                changed_files=["README.md"],
                checks=[],
                follow_up=[],
            ),
            session_id="session-resumed",
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=ado_client,
            executor_runner=executor_runner,
            shell_runner=shell_runner,
        )

        run = orchestrator.resume_from_pr_feedback(
            "run-1",
            comments=[
                {
                    "thread_id": 8,
                    "thread_status": "active",
                    "comment_id": 11,
                    "content": "please update the README wording",
                }
            ],
            event_payload={"event_type": "pr.comment.created"},
        )

        self.assertEqual("run-1", run.run_id)
        self.assertEqual("awaiting_review", run.status)
        self.assertEqual("42", run.pr_id)
        self.assertEqual("session-existing", run.session_id)
        self.assertIsNone(executor_runner.calls[0]["resume_session_id"])
        self.assertEqual("run", executor_runner.calls[0]["request"].mode)
        self.assertFalse(executor_runner.calls[0]["request"].thread)
        self.assertIsNone(executor_runner.calls[0]["request"].label)
        self.assertIn(("commit_and_push", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        reply_calls = [call for call in ado_client.calls if call[0] == "reply_to_pull_request"]
        self.assertEqual(1, len(reply_calls))
        self.assertIn("Addressed the requested README update.", reply_calls[0][1]["content"])
        self.assertNotIn(("create_pull_request", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("pr_feedback_loaded", audit_events)
        self.assertIn("pr_feedback_executor_completed", audit_events)
        self.assertIn("pr_feedback_published", audit_events)
        self.assertIn("pr_feedback_replied", audit_events)

    def test_resume_from_ci_failure_retries_build_and_updates_run(self) -> None:
        self.create_run(
            status="awaiting_ci",
            ci_run_id="99",
            branch_name="refs/heads/ai/123-update-the-readme",
            workspace_path=str(self.workspace),
            session_id="session-existing",
        )
        shell_runner = RecordingShellRunner()
        shell_runner.queue()
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            ExecutorResult(
                status="completed",
                summary="Fixed the failing CI issue.",
                changed_files=["README.md"],
                checks=[],
                follow_up=[],
            ),
            session_id="session-ci-recovery",
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=ado_client,
            executor_runner=executor_runner,
            shell_runner=shell_runner,
        )

        run = orchestrator.resume_from_ci_failure(
            "run-1",
            build_summary={"id": 99, "result": "failed", "definition": {"id": 7}},
            event_payload={"event_type": "ci.run.failed"},
        )

        self.assertEqual("awaiting_ci", run.status)
        self.assertEqual("101", run.ci_run_id)
        self.assertEqual("session-existing", run.session_id)
        self.assertIsNone(executor_runner.calls[0]["resume_session_id"])
        self.assertEqual("run", executor_runner.calls[0]["request"].mode)
        self.assertFalse(executor_runner.calls[0]["request"].thread)
        self.assertIsNone(executor_runner.calls[0]["request"].label)
        self.assertIn(("commit_and_push", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        self.assertIn(("retry_build", "99"), ado_client.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("ci_recovery_loaded", audit_events)
        self.assertIn("ci_recovery_executor_completed", audit_events)
        self.assertIn("ci_retry_requested", audit_events)

    def test_resume_from_ci_failure_escalates_when_executor_requires_human(self) -> None:
        self.create_run(
            status="awaiting_ci",
            ci_run_id="99",
            branch_name="refs/heads/ai/123-update-the-readme",
            workspace_path=str(self.workspace),
            session_id="session-existing",
        )
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            ExecutorResult(
                status="needs_human",
                summary="The build failure is due to external infrastructure instability.",
                changed_files=[],
                checks=[],
                follow_up=["wait for infra owner"],
            ),
            session_id="session-ci-recovery",
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=ado_client,
            executor_runner=executor_runner,
        )

        run = orchestrator.resume_from_ci_failure(
            "run-1",
            build_summary={"id": 99, "result": "failed", "definition": {"id": 7}},
            event_payload={"event_type": "ci.run.failed"},
        )

        self.assertEqual("awaiting_human", run.status)
        self.assertEqual("The build failure is due to external infrastructure instability.", run.last_error)
        self.assertNotIn(("commit_and_push", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        self.assertNotIn(("retry_build", "99"), ado_client.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("ci_recovery_executor_completed", audit_events)
        self.assertIn("run_blocked", audit_events)


if __name__ == "__main__":
    unittest.main()
