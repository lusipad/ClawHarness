from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ado_client import AzureDevOpsApiError, AzureDevOpsRestClient
from codex_acp_runner import CodexAcpRunner, ExecutorRequest, ExecutorRunError, ExecutorRunOutcome
from rocketchat_notifier import RocketChatNotifier, RocketChatNotifierError
from run_store import ClaimRequest, RunStore, StatusTransitionError, TaskRun

from .config import HarnessRuntimeConfig


ShellRunner = Callable[[list[str], str | Path | None, Mapping[str, str] | None], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CheckCommand:
    name: str
    argv: list[str]


@dataclass(frozen=True)
class PublishOutcome:
    branch_name: str
    commit_sha: str | None
    pushed: bool
    created_commit: bool


class TaskOrchestratorError(RuntimeError):
    pass


class TaskRunOrchestrator:
    def __init__(
        self,
        *,
        config: HarnessRuntimeConfig,
        store: RunStore,
        ado_client: AzureDevOpsRestClient,
        executor_runner: CodexAcpRunner,
        notifier: RocketChatNotifier | None = None,
        shell_runner: ShellRunner | None = None,
    ):
        self.config = config
        self.store = store
        self.ado_client = ado_client
        self.executor_runner = executor_runner
        self.notifier = notifier
        self.shell_runner = shell_runner or self._default_shell_runner

    def claim_manual_task(
        self,
        *,
        task_id: str,
        repo_id: str,
        source_id: str | None = None,
        task_context: Mapping[str, Any] | None = None,
    ) -> tuple[TaskRun, dict[str, Any]]:
        context = dict(task_context) if task_context is not None else self._load_task_context(task_id)
        task_key = self._derive_task_key(task_id, context)
        run = TaskRun(
            run_id=self._manual_run_id(task_key),
            provider_type="azure-devops",
            task_id=str(task_id),
            task_key=task_key,
            session_id=self._manual_session_id(task_key),
            executor_type=self.config.executor.mode,
            status="claimed",
            repo_id=repo_id,
        )
        claim = self.store.claim_run(
            ClaimRequest(
                fingerprint=f"manual:{source_id or task_id}",
                source_type="task.manual",
                source_id=source_id,
                owner=self.config.owner,
                dedupe_ttl_seconds=self.config.runtime.dedupe_ttl_seconds,
                lock_ttl_seconds=self.config.runtime.lock_ttl_seconds,
                run=run,
            )
        )
        if not claim.accepted or claim.run is None:
            raise TaskOrchestratorError(f"Could not claim task {task_key}: {claim.reason}")
        return claim.run, context

    def run_claimed_task(
        self,
        run_id: str,
        *,
        task_context: Mapping[str, Any] | None = None,
    ) -> TaskRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise TaskOrchestratorError(f"Run not found: {run_id}")
        if not run.repo_id:
            raise TaskOrchestratorError(f"Run {run_id} is missing repo_id")

        context = dict(task_context) if task_context is not None else self._load_task_context(run.task_id)
        current = run
        try:
            current = self._transition(current.run_id, to_status="planning", expected_from=("claimed", "planning"))
            preparation = self.ado_client.prepare_workspace(
                current.repo_id,
                workspace_root=self.config.runtime.workspace_root,
                run_id=current.run_id,
            )
            branch_name = self._build_branch_name(current.task_id, current.task_key, context)
            branch_ref = self.ado_client.create_branch(
                preparation.workspace_path,
                branch_name=branch_name,
                base_branch=preparation.base_branch,
            )
            current = self.store.update_run_fields(
                current.run_id,
                repo_id=preparation.repository.repository_id,
                workspace_path=preparation.workspace_path,
                branch_name=branch_ref,
            )
            self.store.append_audit(
                current.run_id,
                "workspace_prepared",
                payload={
                    "workspace_path": preparation.workspace_path,
                    "base_branch": preparation.base_branch,
                    "branch_name": branch_ref,
                },
            )

            current = self._transition(current.run_id, to_status="coding", expected_from=("planning", "coding"))
            execution = self._run_executor(current, context)
            current = self._persist_executor_session(current, execution)
            self.store.append_audit(
                current.run_id,
                "executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                },
            )

            checks = self._run_checks(preparation.workspace_path, execution.result.changed_files)
            all_checks = execution.result.checks + checks
            self.store.append_audit(
                current.run_id,
                "checks_completed",
                payload={"checks": all_checks},
            )
            failed_checks = [item for item in all_checks if item.get("status") != "passed"]
            if failed_checks:
                return self._block_run(
                    current.run_id,
                    reason="Checks failed before PR creation",
                    details={"checks": failed_checks},
                )

            current = self._transition(current.run_id, to_status="opening_pr", expected_from="coding")
            commit = self.ado_client.commit_and_push(
                preparation.workspace_path,
                branch_name=branch_ref,
                commit_message=self._build_commit_message(current.task_key, context),
            )
            self.store.append_audit(
                current.run_id,
                "branch_pushed",
                payload={"branch_name": commit.branch_name, "commit_sha": commit.commit_sha},
            )
            pr = self.ado_client.create_pull_request(
                current.repo_id,
                source_branch=commit.branch_name,
                target_branch=preparation.base_branch,
                title=self._build_pr_title(current.task_key, context),
                description=self._build_pr_description(current, execution),
            )
            pr_id = pr.get("pullRequestId")
            current = self.store.update_run_fields(
                current.run_id,
                pr_id=str(pr_id) if pr_id is not None else None,
            )
            current = self._transition(current.run_id, to_status="awaiting_review", expected_from="opening_pr")
            self._notify(
                event_type="pr_opened",
                task_key=current.task_key,
                run_id=current.run_id,
                summary=f"PR opened for {current.task_key}",
                details={
                    "branch": commit.branch_name,
                    "commit": commit.commit_sha,
                    "pr_id": pr_id,
                },
            )
            self._safe_add_task_comment(
                current.task_id,
                f"ClawHarness opened PR {pr_id} from `{commit.branch_name}`.",
            )
            return self.store.get_run(current.run_id) or current
        except Exception as exc:
            return self._block_run(
                run_id,
                reason=str(exc),
                details={"error_type": type(exc).__name__},
            )

    def resume_from_pr_feedback(
        self,
        run_id: str,
        *,
        comments: list[dict[str, Any]] | None = None,
        event_payload: Mapping[str, Any] | None = None,
    ) -> TaskRun:
        current = self._require_run(
            run_id,
            required_fields=("repo_id", "pr_id", "workspace_path", "branch_name"),
        )
        task_context = self._load_task_context(current.task_id)
        all_comments = list(comments or [])
        unresolved_comments = self._collect_unresolved_review_comments(all_comments)

        try:
            current = self._transition(
                current.run_id,
                to_status="coding",
                expected_from=("awaiting_review", "awaiting_ci", "awaiting_human", "planning", "coding"),
            )
            self.store.append_audit(
                current.run_id,
                "pr_feedback_loaded",
                payload={
                    "comment_count": len(all_comments),
                    "unresolved_count": len(unresolved_comments),
                    "event_type": self._event_type(event_payload),
                },
            )

            execution = self._run_resume_executor(
                current,
                task_context=task_context,
                artifact_name="pr-feedback-result.json",
                task_prompt=self._build_pr_feedback_prompt(current, task_context, unresolved_comments),
                constraints=[
                    "Process unresolved PR feedback in the existing branch.",
                    "Reuse the current workspace and session.",
                    "Run relevant local checks before finishing.",
                    "Do not commit, push, or open a new PR directly; the harness owns release actions.",
                    "Do not open a new PR; update the existing PR only.",
                ],
                extra_artifacts={
                    "event": dict(event_payload or {}),
                    "comments": all_comments,
                    "unresolved_comments": unresolved_comments,
                },
            )
            self.store.append_audit(
                current.run_id,
                "pr_feedback_executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                },
            )

            checks = self._run_checks(current.workspace_path or "", execution.result.changed_files)
            all_checks = execution.result.checks + checks
            self.store.append_audit(
                current.run_id,
                "checks_completed",
                payload={"checks": all_checks},
            )
            failed_checks = [item for item in all_checks if item.get("status") != "passed"]
            if failed_checks:
                return self._block_run(
                    current.run_id,
                    reason="Checks failed while applying PR feedback",
                    details={"checks": failed_checks},
                )

            publish = self._publish_resume_changes(
                current,
                commit_message=self._build_resume_commit_message(current.task_key, "Address review feedback"),
            )
            self.store.append_audit(
                current.run_id,
                "pr_feedback_published",
                payload={
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                    "created_commit": publish.created_commit,
                },
            )

            reply_count = self._reply_to_review_threads(
                current,
                unresolved_comments,
                self._build_pr_feedback_reply(current, execution, all_checks, publish),
            )
            if reply_count:
                self.store.append_audit(
                    current.run_id,
                    "pr_feedback_replied",
                    payload={"reply_count": reply_count},
                )

            current = self._transition(
                current.run_id,
                to_status="awaiting_review",
                expected_from=("coding", "awaiting_ci", "awaiting_review"),
            )
            self._notify(
                event_type="pr_feedback_applied",
                task_key=current.task_key,
                run_id=current.run_id,
                summary=f"PR feedback applied for {current.task_key}",
                details={
                    "pr_id": current.pr_id,
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                },
            )
            return self.store.get_run(current.run_id) or current
        except Exception as exc:
            return self._block_run(
                current.run_id,
                reason=str(exc),
                details={"error_type": type(exc).__name__, "phase": "pr_feedback"},
            )

    def resume_from_ci_failure(
        self,
        run_id: str,
        *,
        build_summary: Mapping[str, Any] | None = None,
        event_payload: Mapping[str, Any] | None = None,
    ) -> TaskRun:
        current = self._require_run(
            run_id,
            required_fields=("repo_id", "ci_run_id", "workspace_path", "branch_name"),
        )
        task_context = self._load_task_context(current.task_id)
        summary = dict(build_summary or {})

        try:
            current = self._transition(
                current.run_id,
                to_status="coding",
                expected_from=("awaiting_ci", "awaiting_review", "awaiting_human", "planning", "coding"),
            )
            self.store.append_audit(
                current.run_id,
                "ci_recovery_loaded",
                payload={
                    "ci_run_id": current.ci_run_id,
                    "build_result": summary.get("result"),
                    "event_type": self._event_type(event_payload),
                },
            )

            execution = self._run_resume_executor(
                current,
                task_context=task_context,
                artifact_name="ci-recovery-result.json",
                task_prompt=self._build_ci_recovery_prompt(current, task_context, summary),
                constraints=[
                    "Decide whether the CI failure is recoverable in the current workspace.",
                    'Use status "completed" only when the run is patch-and-retry ready.',
                    'Use status "needs_human" when the failure cannot be safely recovered automatically.',
                    "Run relevant local checks before finishing if you make changes.",
                    "Do not commit or push directly; the harness owns release actions.",
                ],
                extra_artifacts={
                    "event": dict(event_payload or {}),
                    "build_summary": summary,
                },
            )
            self.store.append_audit(
                current.run_id,
                "ci_recovery_executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                },
            )

            if self._is_human_escalation(execution.result.status):
                return self._block_run(
                    current.run_id,
                    reason=execution.result.summary or "CI failure requires human intervention",
                    details={
                        "phase": "ci_recovery",
                        "build_summary": summary,
                        "follow_up": execution.result.follow_up,
                    },
                )

            checks = self._run_checks(current.workspace_path or "", execution.result.changed_files)
            all_checks = execution.result.checks + checks
            self.store.append_audit(
                current.run_id,
                "checks_completed",
                payload={"checks": all_checks},
            )
            failed_checks = [item for item in all_checks if item.get("status") != "passed"]
            if failed_checks:
                return self._block_run(
                    current.run_id,
                    reason="Checks failed while recovering CI",
                    details={"checks": failed_checks},
                )

            publish = self._publish_resume_changes(
                current,
                commit_message=self._build_resume_commit_message(current.task_key, "Recover CI failure"),
            )
            self.store.append_audit(
                current.run_id,
                "ci_recovery_published",
                payload={
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                    "created_commit": publish.created_commit,
                },
            )

            previous_ci_run_id = current.ci_run_id
            retried_build = self.ado_client.retry_build(previous_ci_run_id or "")
            retried_build_id = retried_build.get("id")
            if retried_build_id is not None:
                current = self.store.update_run_fields(current.run_id, ci_run_id=str(retried_build_id))
            self.store.append_audit(
                current.run_id,
                "ci_retry_requested",
                payload={
                    "previous_ci_run_id": previous_ci_run_id,
                    "retry_build_id": str(retried_build_id) if retried_build_id is not None else None,
                    "pushed": publish.pushed,
                },
            )

            current = self._transition(current.run_id, to_status="awaiting_ci", expected_from=("coding", "awaiting_review"))
            self._notify(
                event_type="ci_recovery_started",
                task_key=current.task_key,
                run_id=current.run_id,
                summary=f"CI recovery pushed for {current.task_key}",
                details={
                    "ci_run_id": current.ci_run_id,
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                },
            )
            return self.store.get_run(current.run_id) or current
        except Exception as exc:
            return self._block_run(
                current.run_id,
                reason=str(exc),
                details={"error_type": type(exc).__name__, "phase": "ci_recovery"},
            )

    def _run_executor(self, run: TaskRun, task_context: Mapping[str, Any]) -> ExecutorRunOutcome:
        result_path = self._executor_result_path(run.run_id, "executor-result.json")
        return self._run_executor_request(
            run,
            task_context=task_context,
            result_path=result_path,
            task_prompt=self._build_executor_prompt(run, task_context, result_path),
            constraints=[
                "Use existing repository patterns.",
                "Run relevant local checks before finishing.",
                "Do not push or open the PR directly; the harness owns release actions.",
            ],
        )

    def _run_resume_executor(
        self,
        run: TaskRun,
        *,
        task_context: Mapping[str, Any],
        artifact_name: str,
        task_prompt: str,
        constraints: list[str],
        extra_artifacts: Mapping[str, Any] | None = None,
    ) -> ExecutorRunOutcome:
        result_path = self._executor_result_path(run.run_id, artifact_name)
        return self._run_executor_request(
            run,
            task_context=task_context,
            result_path=result_path,
            task_prompt=task_prompt,
            constraints=constraints,
            extra_artifacts=extra_artifacts,
            use_default_label=False,
        )

    def _run_executor_request(
        self,
        run: TaskRun,
        *,
        task_context: Mapping[str, Any],
        result_path: Path,
        task_prompt: str,
        constraints: list[str],
        extra_artifacts: Mapping[str, Any] | None = None,
        resume_session_id: str | None = None,
        use_default_label: bool = True,
    ) -> ExecutorRunOutcome:
        if run.workspace_path is None:
            raise TaskOrchestratorError(f"Run {run.run_id} is missing workspace_path")

        workspace = Path(run.workspace_path)
        if result_path.exists():
            result_path.unlink()

        artifacts = {
            "task": task_context,
            "run": {
                "run_id": run.run_id,
                "task_key": run.task_key,
                "branch_name": run.branch_name,
                "pr_id": run.pr_id,
                "ci_run_id": run.ci_run_id,
                "session_id": run.session_id,
            },
            "result_path": str(result_path),
        }
        if extra_artifacts:
            artifacts.update(dict(extra_artifacts))

        request = ExecutorRequest(
            workspace_path=str(workspace),
            task_prompt=task_prompt,
            constraints=constraints,
            artifacts=artifacts,
            label=run.task_key if use_default_label else None,
            mode="run",
            thread=False,
        )
        return self.executor_runner.run_and_wait(
            request,
            result_path=result_path,
            timeout_seconds=self.config.executor.timeout_seconds,
            poll_interval_seconds=1.0,
            resume_session_id=resume_session_id,
        )

    def _executor_result_path(self, run_id: str, artifact_name: str) -> Path:
        artifact_dir = Path(self.config.runtime.workspace_root) / ".executor-artifacts" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir / artifact_name

    def _persist_executor_session(self, run: TaskRun, execution: ExecutorRunOutcome) -> TaskRun:
        session_id = execution.spawn.session_id
        if not session_id or session_id == run.session_id:
            return self.store.get_run(run.run_id) or run

        updated = self.store.update_run_fields(run.run_id, session_id=session_id)
        self.store.append_audit(
            run.run_id,
            "executor_session_updated",
            payload={"previous_session_id": run.session_id, "session_id": session_id},
        )
        return updated

    def _require_run(self, run_id: str, *, required_fields: tuple[str, ...] = ()) -> TaskRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise TaskOrchestratorError(f"Run not found: {run_id}")

        missing = [field for field in required_fields if not getattr(run, field)]
        if missing:
            raise TaskOrchestratorError(f"Run {run_id} is missing required fields: {', '.join(missing)}")
        return run

    def _collect_unresolved_review_comments(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unresolved_statuses = {"active", "pending", "unresolved"}
        unresolved: list[dict[str, Any]] = []
        for comment in comments:
            status = str(comment.get("thread_status") or "").strip().lower()
            if status and status not in unresolved_statuses:
                continue
            content = comment.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            unresolved.append(comment)
        return unresolved

    def _publish_resume_changes(self, run: TaskRun, *, commit_message: str) -> PublishOutcome:
        if run.workspace_path is None or run.branch_name is None:
            raise TaskOrchestratorError(f"Run {run.run_id} is missing workspace publish details")

        try:
            commit = self.ado_client.commit_and_push(
                run.workspace_path,
                branch_name=run.branch_name,
                commit_message=commit_message,
            )
            self.store.append_audit(
                run.run_id,
                "branch_pushed",
                payload={"branch_name": commit.branch_name, "commit_sha": commit.commit_sha},
            )
            return PublishOutcome(
                branch_name=commit.branch_name,
                commit_sha=commit.commit_sha,
                pushed=True,
                created_commit=commit.created_commit,
            )
        except AzureDevOpsApiError as exc:
            if "No changes to commit" not in str(exc):
                raise
            self.store.append_audit(
                run.run_id,
                "resume_publish_skipped",
                payload={"reason": "no_changes_to_commit", "branch_name": run.branch_name},
            )
            return PublishOutcome(
                branch_name=run.branch_name,
                commit_sha=None,
                pushed=False,
                created_commit=False,
            )

    def _build_pr_feedback_prompt(
        self,
        run: TaskRun,
        task_context: Mapping[str, Any],
        unresolved_comments: list[dict[str, Any]],
    ) -> str:
        return "\n".join(
            [
                f"Resume run `{run.run_id}` for PR feedback on `{run.task_key}`.",
                f"Existing PR id: {run.pr_id}",
                f"Existing branch: {run.branch_name}",
                "",
                "Required workflow:",
                "1. Review unresolved PR feedback.",
                "2. Patch the existing workspace and branch.",
                "3. Run relevant local checks.",
                '4. Write a structured result where status is "completed" after the feedback is addressed.',
                "5. Leave commit, push, and PR reply steps to the harness.",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
                "",
                "Unresolved review comments:",
                "```json",
                json.dumps(unresolved_comments, indent=2, sort_keys=True),
                "```",
            ]
        )

    def _build_ci_recovery_prompt(
        self,
        run: TaskRun,
        task_context: Mapping[str, Any],
        build_summary: Mapping[str, Any],
    ) -> str:
        return "\n".join(
            [
                f"Resume run `{run.run_id}` for CI recovery on `{run.task_key}`.",
                f"Existing CI run id: {run.ci_run_id}",
                f"Existing branch: {run.branch_name}",
                "",
                "Required workflow:",
                "1. Inspect the failed CI summary.",
                "2. Decide whether the failure is safely recoverable.",
                "3. If recoverable, patch the existing workspace and branch and run checks.",
                '4. If not recoverable, write a structured result with status "needs_human" and explain why.',
                "5. Leave commit, push, and CI retry steps to the harness.",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
                "",
                "Build summary:",
                "```json",
                json.dumps(dict(build_summary), indent=2, sort_keys=True),
                "```",
            ]
        )

    def _build_resume_commit_message(self, task_key: str, action: str) -> str:
        return f"{task_key}: {action}"

    def _build_pr_feedback_reply(
        self,
        run: TaskRun,
        execution: ExecutorRunOutcome,
        checks: list[dict[str, Any]],
        publish: PublishOutcome,
    ) -> str:
        lines = [
            f"ClawHarness applied follow-up updates for `{run.task_key}`.",
            "",
            execution.result.summary or "Feedback has been processed.",
        ]
        if publish.pushed:
            lines.append("")
            lines.append(f"Updated branch: `{publish.branch_name}`")
            if publish.commit_sha:
                lines.append(f"Commit: `{publish.commit_sha}`")
        passed = [item.get("name") for item in checks if item.get("status") == "passed" and item.get("name")]
        if passed:
            lines.append("")
            lines.append("Checks passed:")
            lines.extend(f"- {name}" for name in passed)
        return "\n".join(lines)

    def _reply_to_review_threads(
        self,
        run: TaskRun,
        comments: list[dict[str, Any]],
        content: str,
    ) -> int:
        if not run.repo_id or not run.pr_id:
            return 0

        replied = 0
        replied_threads: set[str] = set()
        for comment in comments:
            thread_id = comment.get("thread_id")
            if thread_id is None:
                continue
            thread_key = str(thread_id)
            if thread_key in replied_threads:
                continue
            parent_comment_id = self._coerce_int(comment.get("comment_id")) or 0
            self.ado_client.reply_to_pull_request(
                run.repo_id,
                run.pr_id,
                thread_id=thread_key,
                parent_comment_id=parent_comment_id,
                content=content,
            )
            replied_threads.add(thread_key)
            replied += 1
        return replied

    def _is_human_escalation(self, status: str) -> bool:
        normalized = status.strip().lower()
        return normalized not in {"completed", "patched", "recovered", "success"}

    def _event_type(self, event_payload: Mapping[str, Any] | None) -> str | None:
        if event_payload is None:
            return None
        value = event_payload.get("event_type")
        return str(value) if value is not None else None

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _run_checks(self, workspace_path: str | Path, changed_files: list[str]) -> list[dict[str, Any]]:
        workspace = Path(workspace_path)
        results: list[dict[str, Any]] = []
        for check in self._build_check_commands(workspace, changed_files):
            completed = self.shell_runner(check.argv, workspace, {"GIT_TERMINAL_PROMPT": "0"})
            status = "passed" if completed.returncode == 0 else "failed"
            results.append(
                {
                    "name": check.name,
                    "command": " ".join(check.argv),
                    "status": status,
                    "exit_code": completed.returncode,
                    "stdout": self._truncate_output(completed.stdout),
                    "stderr": self._truncate_output(completed.stderr),
                }
            )
        return results

    def _build_check_commands(self, workspace: Path, changed_files: list[str]) -> list[CheckCommand]:
        commands: list[CheckCommand] = [CheckCommand(name="git diff --check", argv=["git", "diff", "--check"])]
        seen: set[str] = {commands[0].name}
        for item in changed_files:
            changed_path = Path(item)
            full_path = changed_path if changed_path.is_absolute() else workspace / changed_path
            if full_path.suffix == ".py":
                name = f"python -m py_compile {changed_path.as_posix()}"
                if name not in seen:
                    commands.append(CheckCommand(name=name, argv=["python", "-m", "py_compile", str(full_path)]))
                    seen.add(name)
            elif full_path.suffix in {".js", ".mjs", ".cjs"}:
                name = f"node --check {changed_path.as_posix()}"
                if name not in seen:
                    commands.append(CheckCommand(name=name, argv=["node", "--check", str(full_path)]))
                    seen.add(name)

        package_json = workspace / "package.json"
        if package_json.exists():
            try:
                package = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                package = {}
            scripts = package.get("scripts")
            if isinstance(scripts, Mapping) and isinstance(scripts.get("test"), str) and scripts.get("test"):
                commands.append(CheckCommand(name="npm test", argv=["npm", "test"]))

        tests_dir = workspace / "tests"
        if tests_dir.exists() and any(path.suffix == ".py" for path in tests_dir.rglob("*.py")):
            name = "python -m unittest discover -s tests -v"
            if name not in seen:
                commands.append(
                    CheckCommand(
                        name=name,
                        argv=["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
                    )
                )
                seen.add(name)
        return commands

    def _build_executor_prompt(self, run: TaskRun, task_context: Mapping[str, Any], result_path: Path) -> str:
        return "\n".join(
            [
                f"Analyze and implement Azure DevOps task `{run.task_key}`.",
                f"Run id: {run.run_id}",
                f"Workspace: {run.workspace_path}",
                "",
                "Required workflow:",
                "1. Produce a concise plan for the task.",
                "2. Implement the changes in the workspace.",
                "3. Run relevant local checks.",
                "4. Write the structured result JSON to the provided artifact path.",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
                "",
                f"Result artifact: {result_path}",
            ]
        )

    def _build_branch_name(self, task_id: str, task_key: str, task_context: Mapping[str, Any]) -> str:
        fields = task_context.get("fields")
        title = ""
        if isinstance(fields, Mapping):
            title_value = fields.get("System.Title")
            if isinstance(title_value, str):
                title = title_value
        suffix = re.sub(r"[^A-Za-z0-9]+", "-", title.lower()).strip("-")[:40]
        branch = f"{self.config.runtime.branch_prefix}/{task_id}"
        if suffix:
            branch = f"{branch}-{suffix}"
        return branch

    def _build_commit_message(self, task_key: str, task_context: Mapping[str, Any]) -> str:
        fields = task_context.get("fields")
        title = ""
        if isinstance(fields, Mapping):
            value = fields.get("System.Title")
            if isinstance(value, str):
                title = value.strip()
        return f"{task_key}: {title or 'ClawHarness update'}"

    def _build_pr_title(self, task_key: str, task_context: Mapping[str, Any]) -> str:
        return self._build_commit_message(task_key, task_context)

    def _build_pr_description(self, run: TaskRun, execution: ExecutorRunOutcome) -> str:
        lines = [
            f"Automated change for `{run.task_key}`.",
            "",
            execution.result.summary or "No summary provided.",
        ]
        if execution.result.follow_up:
            lines.extend(["", "Follow-up:", *[f"- {item}" for item in execution.result.follow_up]])
        return "\n".join(lines)

    def _load_task_context(self, task_id: str) -> dict[str, Any]:
        return self.ado_client.get_task(
            task_id,
            fields=[
                "System.Title",
                "System.Description",
                "System.State",
                "System.TeamProject",
                "System.AssignedTo",
            ],
        )

    def _derive_task_key(self, task_id: str, task_context: Mapping[str, Any]) -> str:
        fields = task_context.get("fields")
        if isinstance(fields, Mapping):
            project = fields.get("System.TeamProject")
            if isinstance(project, str) and project:
                return f"{project}#{task_id}"
        return str(task_id)

    def _manual_run_id(self, task_key: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", task_key).strip("-") or "task"
        return f"manual-{slug.lower()}"

    def _manual_session_id(self, task_key: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._:-]+", "-", task_key).strip("-") or "task"
        return f"manual:{slug.lower()}"

    def _transition(self, run_id: str, *, to_status: str, expected_from: str | tuple[str, ...]) -> TaskRun:
        try:
            return self.store.transition_status(run_id, to_status=to_status, expected_from=expected_from)
        except StatusTransitionError:
            run = self.store.get_run(run_id)
            if run is None:
                raise
            return run

    def _block_run(self, run_id: str, *, reason: str, details: dict[str, Any]) -> TaskRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise TaskOrchestratorError(f"Run not found: {run_id}")
        try:
            blocked = self.store.transition_status(
                run_id,
                to_status="awaiting_human",
                expected_from=(run.status, "claimed", "planning", "coding", "opening_pr"),
                last_error=reason,
                released_lock=True,
            )
        except StatusTransitionError:
            blocked = run
            self.store.append_audit(
                run_id,
                "status_transition_skipped",
                payload={"to_status": "awaiting_human", "reason": reason},
            )
        self.store.append_audit(run_id, "run_blocked", payload={"reason": reason, **details})
        self._notify(
            event_type="task_blocked",
            task_key=blocked.task_key,
            run_id=blocked.run_id,
            summary=f"Run {blocked.task_key} blocked",
            details={"reason": reason, **details},
        )
        return self.store.get_run(run_id) or blocked

    def _notify(
        self,
        *,
        event_type: str,
        task_key: str,
        run_id: str,
        summary: str,
        details: dict[str, Any],
    ) -> None:
        if self.notifier is None:
            return
        try:
            self.notifier.notify_lifecycle(
                event_type=event_type,
                task_key=task_key,
                run_id=run_id,
                summary=summary,
                details=details,
            )
        except RocketChatNotifierError:
            self.store.append_audit(
                run_id,
                "notification_failed",
                payload={"provider": "rocketchat", "event_type": event_type},
            )

    def _safe_add_task_comment(self, task_id: str, text: str) -> None:
        try:
            self.ado_client.add_task_comment(task_id, text)
        except AzureDevOpsApiError:
            return

    def _truncate_output(self, value: str | None, limit: int = 4000) -> str:
        text = (value or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "...<truncated>"

    def _default_shell_runner(
        self,
        command: list[str],
        cwd: str | Path | None,
        env_overrides: Mapping[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
