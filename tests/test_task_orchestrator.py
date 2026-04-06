from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
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
    def __init__(
        self,
        result: ExecutorResult | list[ExecutorResult],
        *,
        session_id: str = "session-1",
        session_ids: list[str] | None = None,
    ) -> None:
        results = result if isinstance(result, list) else [result]
        ids = session_ids if session_ids is not None else [session_id] * len(results)
        if len(results) != len(ids):
            raise ValueError("results and session_ids must have the same length")
        self.responses = list(zip(results, ids, strict=True))
        self.calls: list[dict[str, object]] = []

    def run_and_wait(self, request, *, result_path, timeout_seconds, poll_interval_seconds, resume_session_id=None):
        if not self.responses:
            raise AssertionError("No queued executor response")
        result, session_id = self.responses.pop(0)
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
                session_id=session_id,
            ),
            result=result,
        )


class FakeAdoClient:
    provider_type = "azure-devops"
    display_name = "Azure DevOps"

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

    def add_task_comment(self, work_item_id: int | str, text: str, *, repo_id: str | None = None) -> dict[str, object]:
        self.calls.append(("add_task_comment", {"work_item_id": str(work_item_id), "repo_id": repo_id}))
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

    def get_task(self, work_item_id: int | str, *, repo_id=None, fields=None, expand=None, as_of=None) -> dict[str, object]:
        self.calls.append(
            (
                "get_task",
                {
                    "work_item_id": str(work_item_id),
                    "repo_id": repo_id,
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

    def retry_ci_run(self, build_id: int | str, *, repo_id: str | None = None) -> dict[str, object]:
        self.calls.append(("retry_ci_run", {"build_id": str(build_id), "repo_id": repo_id}))
        return {"id": 101, "status": "notStarted"}


class FakeGitHubClient:
    provider_type = "github"
    display_name = "GitHub"

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.calls: list[tuple[str, object]] = []

    def prepare_workspace(self, repository_id: str, *, workspace_root: str | Path, run_id: str) -> WorkspacePreparationResult:
        self.calls.append(("prepare_workspace", repository_id))
        return WorkspacePreparationResult(
            repository=RepositoryInfo(
                repository_id=repository_id,
                name="ClawHarness",
                default_branch="refs/heads/main",
                remote_url="https://github.com/lusipad/ClawHarness.git",
                web_url="https://github.com/lusipad/ClawHarness",
            ),
            workspace_path=str(self.workspace_path),
            base_branch="refs/heads/main",
        )

    def create_branch(self, workspace_path: str | Path, *, branch_name: str, base_branch: str) -> str:
        self.calls.append(("create_branch", {"branch_name": branch_name, "base_branch": base_branch}))
        return f"refs/heads/{branch_name}"

    def commit_and_push(self, workspace_path: str | Path, *, branch_name: str, commit_message: str) -> CommitPushResult:
        self.calls.append(("commit_and_push", {"branch_name": branch_name, "commit_message": commit_message}))
        return CommitPushResult(
            branch_name=branch_name,
            commit_sha="def456",
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
        self.calls.append(
            (
                "create_pull_request",
                {
                    "repository_id": repository_id,
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "title": title,
                    "description": description,
                },
            )
        )
        return {"number": 77, "html_url": "https://github.com/lusipad/ClawHarness/pull/77"}

    def add_task_comment(self, work_item_id: int | str, text: str, *, repo_id: str | None = None) -> dict[str, object]:
        self.calls.append(("add_task_comment", {"task_id": str(work_item_id), "repo_id": repo_id, "text": text}))
        return {"id": 2}

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
        return {"id": 8}

    def get_task(self, work_item_id: int | str, *, repo_id=None, fields=None, expand=None, as_of=None) -> dict[str, object]:
        self.calls.append(
            (
                "get_task",
                {
                    "work_item_id": str(work_item_id),
                    "repo_id": repo_id,
                    "fields": list(fields) if fields is not None else None,
                    "expand": expand,
                    "as_of": as_of,
                },
            )
        )
        return {
            "id": int(work_item_id),
            "fields": {
                "System.TeamProject": repo_id or "lusipad/ClawHarness",
                "System.Title": "Implement GitHub workflow",
                "System.Description": "Drive the same loop through GitHub.",
            },
        }

    def retry_ci_run(self, ci_run_id: int | str, *, repo_id: str | None = None) -> dict[str, object]:
        self.calls.append(("retry_ci_run", {"ci_run_id": str(ci_run_id), "repo_id": repo_id}))
        return {"id": "check-run:202"}


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
            readonly_token=None,
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
            [
                ExecutorResult(
                    status="completed",
                    summary="Plan the README update and validate markdown formatting.",
                    changed_files=[],
                    checks=[],
                    follow_up=["update README.md", "run git diff --check"],
                ),
                ExecutorResult(
                    status="completed",
                    summary="Updated the README with validation notes.",
                    changed_files=["README.md"],
                    checks=[],
                    follow_up=["wait for review"],
                ),
                ExecutorResult(
                    status="approved",
                    summary="Review passed with no blocking issues.",
                    changed_files=[],
                    checks=[],
                    follow_up=[],
                ),
                ExecutorResult(
                    status="passed",
                    summary="Verification passed and the task is ready for PR creation.",
                    changed_files=[],
                    checks=[],
                    follow_up=[],
                ),
            ],
            session_ids=["session-plan", "session-exec", "session-review", "session-verify"],
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
        self.assertEqual("session-exec", run.session_id)
        self.assertTrue(run.branch_name.startswith("refs/heads/ai/123"))
        result_path = Path(executor_runner.calls[0]["result_path"])
        self.assertTrue(result_path.is_absolute())
        self.assertNotIn(self.workspace, result_path.parents)
        self.assertEqual(4, len(executor_runner.calls))
        self.assertEqual(
            ["git", "-c", "core.whitespace=cr-at-eol", "diff", "--check"],
            shell_runner.calls[0]["command"],
        )
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("workspace_prepared", audit_events)
        self.assertIn("agent_result_recorded", audit_events)
        self.assertIn("executor_completed", audit_events)
        self.assertIn("executor_session_updated", audit_events)
        self.assertIn("checks_completed", audit_events)
        self.assertIn(("create_pull_request", run.branch_name), ado_client.calls)
        checkpoints = self.store.list_checkpoints("run-1")
        self.assertEqual(
            ["planning", "workspace_prepared", "coding", "executor_completed", "verification", "awaiting_review"],
            [entry["stage"] for entry in checkpoints],
        )
        artifacts = self.store.list_artifacts("run-1")
        self.assertEqual(
            ["task-context", "executor-result", "check-report", "git-push", "pull-request"],
            [entry["artifact_type"] for entry in artifacts],
        )
        check_report = next(item for item in artifacts if item["artifact_type"] == "check-report")
        check_payload = json.loads(check_report["payload_json"])
        self.assertEqual("git diff --check", check_payload["checks"][0]["name"])
        self.assertEqual("git -c core.whitespace=cr-at-eol diff --check", check_payload["checks"][0]["command"])
        child_links = self.store.list_child_relationships("run-1")
        self.assertEqual(
            ["agent-verifier", "agent-reviewer", "agent-executor", "agent-planner"],
            [link["relation_type"] for link in child_links],
        )
        self.assertEqual(
            ["completed", "completed", "completed", "completed"],
            [link["run"].status for link in child_links],
        )
        planner_child = next(link["run"] for link in child_links if link["relation_type"] == "agent-planner")
        executor_child = next(link["run"] for link in child_links if link["relation_type"] == "agent-executor")
        planner_selection = self.store.list_skill_selections(planner_child.run_id)
        executor_selection = self.store.list_skill_selections(executor_child.run_id)
        self.assertEqual("planner", planner_selection[0]["agent_role"])
        self.assertIn("analyze-task", planner_selection[0]["payload_json"])
        self.assertEqual("executor", executor_selection[0]["agent_role"])
        self.assertIn("implement-task", executor_selection[0]["payload_json"])
        self.assertIn("skill_selection", executor_runner.calls[0]["request"].artifacts)

    def test_run_claimed_task_supports_github_provider_with_shared_workflow(self) -> None:
        self.store.create_run(
            TaskRun(
                run_id="run-gh-1",
                provider_type="github",
                task_id="123",
                task_key="lusipad/ClawHarness#123",
                repo_id="lusipad/ClawHarness",
                session_id="manual:github-123",
                executor_type="codex-acp",
                status="claimed",
            )
        )
        shell_runner = RecordingShellRunner()
        shell_runner.queue()
        github_client = FakeGitHubClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            [
                ExecutorResult(
                    status="completed",
                    summary="Plan the GitHub implementation path.",
                    changed_files=[],
                    checks=[],
                    follow_up=["update README.md"],
                ),
                ExecutorResult(
                    status="completed",
                    summary="Implemented the GitHub workflow change.",
                    changed_files=["README.md"],
                    checks=[],
                    follow_up=[],
                ),
                ExecutorResult(
                    status="approved",
                    summary="Review passed.",
                    changed_files=[],
                    checks=[],
                    follow_up=[],
                ),
                ExecutorResult(
                    status="passed",
                    summary="Verification passed.",
                    changed_files=[],
                    checks=[],
                    follow_up=[],
                ),
            ],
            session_ids=["gh-plan", "gh-exec", "gh-review", "gh-verify"],
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=None,
            provider_clients={"github": github_client},
            executor_runner=executor_runner,
            shell_runner=shell_runner,
        )

        run = orchestrator.run_claimed_task("run-gh-1")

        self.assertEqual("awaiting_review", run.status)
        self.assertEqual("77", run.pr_id)
        self.assertEqual("gh-exec", run.session_id)
        self.assertTrue(run.branch_name.startswith("refs/heads/ai/123"))
        pr_artifact = next(item for item in self.store.list_artifacts("run-gh-1") if item["artifact_type"] == "pull-request")
        self.assertIn('"url":"https://github.com/lusipad/ClawHarness/pull/77"', pr_artifact["payload_json"])
        self.assertIn(
            (
                "create_pull_request",
                {
                    "repository_id": "lusipad/ClawHarness",
                    "source_branch": run.branch_name,
                    "target_branch": "refs/heads/main",
                    "title": "lusipad/ClawHarness#123: Implement GitHub workflow",
                    "description": mock.ANY,
                },
            ),
            github_client.calls,
        )
        self.assertIn(
            (
                "add_task_comment",
                {
                    "task_id": "123",
                    "repo_id": "lusipad/ClawHarness",
                    "text": mock.ANY,
                },
            ),
            github_client.calls,
        )
        child_links = self.store.list_child_relationships("run-gh-1")
        executor_child = next(link["run"] for link in child_links if link["relation_type"] == "agent-executor")
        executor_selection = self.store.list_skill_selections(executor_child.run_id)
        self.assertEqual("task", executor_selection[0]["run_kind"])
        self.assertIn('"provider_type":"github"', executor_selection[0]["payload_json"])

    def test_run_claimed_task_blocks_when_reviewer_rejects_patch(self) -> None:
        self.create_run()
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            [
                ExecutorResult(
                    status="completed",
                    summary="Plan the README update.",
                    changed_files=[],
                    checks=[],
                    follow_up=["update README.md"],
                ),
                ExecutorResult(
                    status="completed",
                    summary="Updated the README with risky wording.",
                    changed_files=["README.md"],
                    checks=[],
                    follow_up=[],
                ),
                ExecutorResult(
                    status="needs_human",
                    summary="The patch changes user-facing wording without product approval.",
                    changed_files=[],
                    checks=[],
                    follow_up=["request copy review"],
                ),
            ],
            session_ids=["session-plan", "session-exec", "session-review"],
        )
        orchestrator = TaskRunOrchestrator(
            config=self.config,
            store=self.store,
            ado_client=ado_client,
            executor_runner=executor_runner,
        )

        run = orchestrator.run_claimed_task("run-1", task_context=self.task_context)

        self.assertEqual("awaiting_human", run.status)
        self.assertIsNone(run.pr_id)
        self.assertEqual("The patch changes user-facing wording without product approval.", run.last_error)
        self.assertNotIn(("create_pull_request", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        blocked_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("agent_remediation_recorded", blocked_events)
        self.assertIn("child_run_blocked", blocked_events)
        child_runs = self.store.list_child_relationships("run-1")
        self.assertEqual(["agent-reviewer", "agent-executor", "agent-planner"], [item["relation_type"] for item in child_runs])
        self.assertEqual("awaiting_human", child_runs[0]["run"].status)

    def test_run_claimed_task_blocks_when_verifier_checks_fail(self) -> None:
        self.create_run()
        shell_runner = RecordingShellRunner()
        shell_runner.queue(returncode=1, stderr="trailing whitespace")
        ado_client = FakeAdoClient(self.workspace)
        executor_runner = FakeExecutorRunner(
            [
                ExecutorResult(
                    status="completed",
                    summary="Plan the README update.",
                    changed_files=[],
                    checks=[],
                    follow_up=["update README.md"],
                ),
                ExecutorResult(
                    status="completed",
                    summary="Updated the README with invalid formatting.",
                    changed_files=["README.md"],
                    checks=[],
                    follow_up=[],
                ),
                ExecutorResult(
                    status="approved",
                    summary="Review passed.",
                    changed_files=[],
                    checks=[],
                    follow_up=[],
                ),
                ExecutorResult(
                    status="passed",
                    summary="Verification logic passed before shell checks.",
                    changed_files=[],
                    checks=[],
                    follow_up=["fix formatting"],
                ),
            ],
            session_ids=["session-plan", "session-exec", "session-review", "session-verify"],
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
        child_runs = self.store.list_child_relationships("run-1")
        self.assertEqual("agent-verifier", child_runs[0]["relation_type"])
        self.assertEqual("awaiting_human", child_runs[0]["run"].status)
        verifier_artifacts = self.store.list_artifacts(child_runs[0]["run"].run_id)
        self.assertIn("check-report", [item["artifact_type"] for item in verifier_artifacts])
        parent_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("agent_remediation_recorded", parent_events)
        self.assertIn("child_run_blocked", parent_events)

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
                    "repo_id": "repo-1",
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

    def test_resume_from_pr_feedback_creates_child_run_and_syncs_parent(self) -> None:
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
        self.assertEqual("session-resumed", run.session_id)
        self.assertEqual("session-existing", executor_runner.calls[0]["resume_session_id"])
        self.assertEqual("run", executor_runner.calls[0]["request"].mode)
        self.assertFalse(executor_runner.calls[0]["request"].thread)
        self.assertIsNone(executor_runner.calls[0]["request"].label)
        self.assertIn(("commit_and_push", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        reply_calls = [call for call in ado_client.calls if call[0] == "reply_to_pull_request"]
        self.assertEqual(1, len(reply_calls))
        self.assertIn("Addressed the requested README update.", reply_calls[0][1]["content"])
        self.assertNotIn(("create_pull_request", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        child_runs = self.store.list_child_runs("run-1")
        self.assertEqual(1, len(child_runs))
        child_run = child_runs[0]
        self.assertEqual("completed", child_run.status)
        self.assertEqual("run-1", self.store.get_parent_run(child_run.run_id).run_id)
        child_audit_events = [entry["event_type"] for entry in self.store.list_audit(child_run.run_id)]
        self.assertIn("pr_feedback_loaded", child_audit_events)
        self.assertIn("pr_feedback_executor_completed", child_audit_events)
        self.assertIn("pr_feedback_published", child_audit_events)
        self.assertIn("pr_feedback_replied", child_audit_events)
        parent_audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("child_run_created", parent_audit_events)
        self.assertIn("child_run_completed", parent_audit_events)
        checkpoints = self.store.list_checkpoints(child_run.run_id)
        self.assertEqual(
            ["claimed", "planning", "coding", "executor_completed", "verification", "completed"],
            [entry["stage"] for entry in checkpoints],
        )
        artifacts = self.store.list_artifacts(child_run.run_id)
        self.assertEqual(
            ["event", "review-comments", "executor-result", "check-report", "git-push"],
            [entry["artifact_type"] for entry in artifacts],
        )
        skill_selections = self.store.list_skill_selections(child_run.run_id)
        self.assertEqual("pr-feedback", skill_selections[0]["run_kind"])
        self.assertEqual("executor", skill_selections[0]["agent_role"])
        self.assertIn("fix-pr-feedback", skill_selections[0]["payload_json"])

    def test_resume_from_ci_failure_creates_child_run_and_updates_parent(self) -> None:
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
        self.assertEqual("session-ci-recovery", run.session_id)
        self.assertEqual("session-existing", executor_runner.calls[0]["resume_session_id"])
        self.assertEqual("run", executor_runner.calls[0]["request"].mode)
        self.assertFalse(executor_runner.calls[0]["request"].thread)
        self.assertIsNone(executor_runner.calls[0]["request"].label)
        self.assertIn(("commit_and_push", "refs/heads/ai/123-update-the-readme"), ado_client.calls)
        self.assertIn(("retry_ci_run", {"build_id": "99", "repo_id": "repo-1"}), ado_client.calls)
        child_runs = self.store.list_child_runs("run-1")
        self.assertEqual(1, len(child_runs))
        child_run = child_runs[0]
        self.assertEqual("completed", child_run.status)
        self.assertEqual("101", child_run.ci_run_id)
        child_audit_events = [entry["event_type"] for entry in self.store.list_audit(child_run.run_id)]
        self.assertIn("ci_recovery_loaded", child_audit_events)
        self.assertIn("ci_recovery_executor_completed", child_audit_events)
        self.assertIn("ci_retry_requested", child_audit_events)
        parent_audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("child_run_created", parent_audit_events)
        self.assertIn("child_run_completed", parent_audit_events)
        checkpoints = self.store.list_checkpoints(child_run.run_id)
        self.assertEqual(
            ["claimed", "planning", "coding", "executor_completed", "verification", "completed"],
            [entry["stage"] for entry in checkpoints],
        )
        artifacts = self.store.list_artifacts(child_run.run_id)
        self.assertEqual(
            ["event", "ci-summary", "executor-result", "check-report", "git-push", "ci-retry"],
            [entry["artifact_type"] for entry in artifacts],
        )
        skill_selections = self.store.list_skill_selections(child_run.run_id)
        self.assertEqual("ci-recovery", skill_selections[0]["run_kind"])
        self.assertIn("recover-ci-failure", skill_selections[0]["payload_json"])

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
        child_runs = self.store.list_child_runs("run-1")
        self.assertEqual(1, len(child_runs))
        child_run = child_runs[0]
        self.assertEqual("awaiting_human", child_run.status)
        child_audit_events = [entry["event_type"] for entry in self.store.list_audit(child_run.run_id)]
        self.assertIn("ci_recovery_executor_completed", child_audit_events)
        self.assertIn("run_blocked", child_audit_events)
        parent_audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertIn("child_run_created", parent_audit_events)
        self.assertIn("child_run_blocked", parent_audit_events)


if __name__ == "__main__":
    unittest.main()
