from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ado_client import AzureDevOpsRestClient
from codex_acp_runner import CodexAcpRunner, ExecutorRequest, ExecutorRunError, ExecutorRunOutcome
from rocketchat_notifier import RocketChatNotifier, RocketChatNotifierError
from run_store import ClaimRequest, RunStore, StatusTransitionError, TaskRun
from workflow_provider import ProviderApiError, WorkflowProviderClient

from .config import HarnessRuntimeConfig
from .skill_registry import SkillRegistry, SkillSelection, load_default_skill_registry


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
        ado_client: AzureDevOpsRestClient | None = None,
        provider_clients: Mapping[str, WorkflowProviderClient] | None = None,
        executor_runner: CodexAcpRunner,
        notifier: RocketChatNotifier | None = None,
        shell_runner: ShellRunner | None = None,
        skill_registry: SkillRegistry | None = None,
    ):
        self.config = config
        self.store = store
        clients = dict(provider_clients or {})
        if ado_client is not None:
            clients.setdefault("azure-devops", ado_client)
        self.provider_clients = clients
        self.ado_client = ado_client or clients.get("azure-devops")
        self.executor_runner = executor_runner
        self.notifier = notifier
        self.shell_runner = shell_runner or self._default_shell_runner
        self.skill_registry = skill_registry or load_default_skill_registry()

    def _is_failing_check(self, check: Mapping[str, Any]) -> bool:
        status = str(check.get("status") or "").strip().lower()
        return status in {"failed", "failure", "error", "blocked", "needs_human", "timed_out", "timeout"}

    def claim_manual_task(
        self,
        *,
        task_id: str,
        repo_id: str,
        provider_type: str | None = None,
        source_id: str | None = None,
        task_context: Mapping[str, Any] | None = None,
    ) -> tuple[TaskRun, dict[str, Any]]:
        effective_provider_type = provider_type or self.config.default_task_provider
        context = (
            dict(task_context)
            if task_context is not None
            else self._load_task_context(task_id, provider_type=effective_provider_type, repo_id=repo_id)
        )
        task_key = self._derive_task_key(task_id, context)
        run = TaskRun(
            run_id=self._manual_run_id(task_key),
            provider_type=effective_provider_type,
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

        provider = self._provider_client(run.provider_type)
        context = (
            dict(task_context)
            if task_context is not None
            else self._load_task_context(run.task_id, provider_type=run.provider_type, repo_id=run.repo_id)
        )
        current = run
        try:
            self._record_artifact(
                current.run_id,
                artifact_type="task-context",
                artifact_name="task-context",
                payload=context,
            )
            current = self._transition(current.run_id, to_status="planning", expected_from=("claimed", "planning"))
            self._record_checkpoint(
                current.run_id,
                "planning",
                payload={"phase": "task_claimed", "task_id": current.task_id, "task_key": current.task_key},
            )
            preparation = provider.prepare_workspace(
                current.repo_id,
                workspace_root=self.config.runtime.workspace_root,
                run_id=current.run_id,
            )
            branch_name = self._build_branch_name(current.task_id, current.task_key, context)
            branch_ref = provider.create_branch(
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
            self._record_checkpoint(
                current.run_id,
                "workspace_prepared",
                payload={
                    "workspace_path": preparation.workspace_path,
                    "base_branch": preparation.base_branch,
                    "branch_name": branch_ref,
                },
            )

            planner_child, planner_execution = self._run_child_agent(
                current,
                task_context=context,
                agent_role="planner",
                artifact_name="planner-result.json",
                task_prompt_builder=lambda child, result_path: self._build_planner_prompt(
                    current,
                    child,
                    context,
                    result_path,
                ),
                constraints=[
                    "Produce a concise implementation plan and validation approach.",
                    "Do not modify files, commit, push, or open PRs.",
                    'Use status "completed" only when the task is sufficiently decomposed for execution.',
                    'Use status "needs_human" when the task cannot be safely planned automatically.',
                ],
                stage="planning",
            )
            if planner_child is None or planner_execution is None:
                return self.store.get_run(current.run_id) or current
            if not self._is_success_status(planner_execution.result.status, allowed={"completed", "planned", "success"}):
                return self._block_agent_child(
                    current,
                    planner_child,
                    agent_role="planner",
                    relation_type="agent-planner",
                    reason=planner_execution.result.summary or "Planner agent could not produce an execution plan",
                    result_status=planner_execution.result.status,
                    follow_up=planner_execution.result.follow_up,
                )
            self._complete_child_run(
                planner_child.run_id,
                parent_run_id=current.run_id,
                parent_status=None,
                sync_parent_session=False,
                completion_payload={
                    "relation_type": "agent-planner",
                    "agent_role": "planner",
                    "result_status": planner_execution.result.status,
                },
            )

            current = self._transition(current.run_id, to_status="coding", expected_from=("planning", "coding"))
            self._record_checkpoint(
                current.run_id,
                "coding",
                payload={
                    "phase": "multi_agent_execution_started",
                    "workspace_path": preparation.workspace_path,
                    "planner_run_id": planner_child.run_id,
                },
            )

            executor_child, execution = self._run_child_agent(
                current,
                task_context=context,
                agent_role="executor",
                artifact_name="executor-result.json",
                task_prompt_builder=lambda child, result_path: self._build_executor_prompt(
                    current,
                    child,
                    context,
                    result_path,
                    planner_execution.result,
                ),
                constraints=[
                    "Use existing repository patterns.",
                    "Run relevant local checks before finishing.",
                    "Do not push or open the PR directly; the harness owns release actions.",
                ],
                stage="coding",
                extra_artifacts={
                    "planner_result": {
                        "status": planner_execution.result.status,
                        "summary": planner_execution.result.summary,
                        "follow_up": planner_execution.result.follow_up,
                    }
                },
            )
            if executor_child is None or execution is None:
                return self.store.get_run(current.run_id) or current
            if not self._is_success_status(
                execution.result.status,
                allowed={"completed", "patched", "implemented", "success"},
            ):
                return self._block_agent_child(
                    current,
                    executor_child,
                    agent_role="executor",
                    relation_type="agent-executor",
                    reason=execution.result.summary or "Executor agent could not complete the implementation",
                    result_status=execution.result.status,
                    follow_up=execution.result.follow_up,
                )

            current = self._promote_child_session(
                current,
                child_run=executor_child,
                session_id=execution.spawn.session_id,
                agent_role="executor",
            )
            self.store.append_audit(
                current.run_id,
                "executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                    "child_run_id": executor_child.run_id,
                },
            )
            self._record_checkpoint(
                current.run_id,
                "executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                    "child_run_id": executor_child.run_id,
                },
            )
            self._record_artifact(
                current.run_id,
                artifact_type="executor-result",
                artifact_name="executor-summary",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                    "follow_up": execution.result.follow_up,
                    "child_run_id": executor_child.run_id,
                },
            )
            self._complete_child_run(
                executor_child.run_id,
                parent_run_id=current.run_id,
                parent_status=None,
                sync_parent_session=False,
                completion_payload={
                    "relation_type": "agent-executor",
                    "agent_role": "executor",
                    "result_status": execution.result.status,
                },
            )

            reviewer_child, reviewer_execution = self._run_child_agent(
                current,
                task_context=context,
                agent_role="reviewer",
                artifact_name="reviewer-result.json",
                task_prompt_builder=lambda child, result_path: self._build_reviewer_prompt(
                    current,
                    child,
                    context,
                    result_path,
                    execution.result,
                ),
                constraints=[
                    "Review the current workspace and branch against the task intent.",
                    "Do not modify files, commit, push, or open PRs.",
                    'Use status "approved" or "completed" only when the change is ready for verification.',
                    'Use status "needs_human" when blocking review issues remain.',
                ],
                stage="coding",
                extra_artifacts={
                    "executor_result": {
                        "status": execution.result.status,
                        "summary": execution.result.summary,
                        "changed_files": execution.result.changed_files,
                        "follow_up": execution.result.follow_up,
                    }
                },
            )
            if reviewer_child is None or reviewer_execution is None:
                return self.store.get_run(current.run_id) or current
            if not self._is_success_status(
                reviewer_execution.result.status,
                allowed={"completed", "approved", "success", "ready"},
            ):
                return self._block_agent_child(
                    current,
                    reviewer_child,
                    agent_role="reviewer",
                    relation_type="agent-reviewer",
                    reason=reviewer_execution.result.summary or "Reviewer agent rejected the current patch",
                    result_status=reviewer_execution.result.status,
                    follow_up=reviewer_execution.result.follow_up,
                )
            self._complete_child_run(
                reviewer_child.run_id,
                parent_run_id=current.run_id,
                parent_status=None,
                sync_parent_session=False,
                completion_payload={
                    "relation_type": "agent-reviewer",
                    "agent_role": "reviewer",
                    "result_status": reviewer_execution.result.status,
                },
            )

            verifier_child, verifier_execution = self._run_child_agent(
                current,
                task_context=context,
                agent_role="verifier",
                artifact_name="verifier-result.json",
                task_prompt_builder=lambda child, result_path: self._build_verifier_prompt(
                    current,
                    child,
                    context,
                    result_path,
                    planner_execution.result,
                    execution.result,
                    reviewer_execution.result,
                ),
                constraints=[
                    "Verify the workspace is ready for PR creation.",
                    "Do not modify files, commit, push, or open PRs.",
                    'Use status "completed", "passed", or "ready" only when the change is ready to publish.',
                    'Use status "needs_human" when verification cannot safely pass.',
                ],
                stage="coding",
                extra_artifacts={
                    "planner_result": {
                        "status": planner_execution.result.status,
                        "summary": planner_execution.result.summary,
                        "follow_up": planner_execution.result.follow_up,
                    },
                    "executor_result": {
                        "status": execution.result.status,
                        "summary": execution.result.summary,
                        "changed_files": execution.result.changed_files,
                        "follow_up": execution.result.follow_up,
                    },
                    "reviewer_result": {
                        "status": reviewer_execution.result.status,
                        "summary": reviewer_execution.result.summary,
                        "follow_up": reviewer_execution.result.follow_up,
                    },
                },
            )
            if verifier_child is None or verifier_execution is None:
                return self.store.get_run(current.run_id) or current
            if not self._is_success_status(
                verifier_execution.result.status,
                allowed={"completed", "passed", "ready", "approved", "success"},
            ):
                return self._block_agent_child(
                    current,
                    verifier_child,
                    agent_role="verifier",
                    relation_type="agent-verifier",
                    reason=verifier_execution.result.summary or "Verifier agent rejected PR publication",
                    result_status=verifier_execution.result.status,
                    follow_up=verifier_execution.result.follow_up,
                )

            checks = self._run_checks(preparation.workspace_path, execution.result.changed_files)
            all_checks = verifier_execution.result.checks + checks
            self.store.append_audit(
                verifier_child.run_id,
                "checks_completed",
                payload={"checks": all_checks},
            )
            self._record_artifact(
                verifier_child.run_id,
                artifact_type="check-report",
                artifact_name="verifier-checks",
                payload={"checks": all_checks},
            )
            failed_checks = [item for item in all_checks if self._is_failing_check(item)]
            self._record_checkpoint(
                verifier_child.run_id,
                "verification",
                payload={
                    "check_count": len(all_checks),
                    "failed_check_count": len(failed_checks),
                },
            )
            if failed_checks:
                return self._block_agent_child(
                    current,
                    verifier_child,
                    agent_role="verifier",
                    relation_type="agent-verifier",
                    reason="Checks failed before PR creation",
                    result_status=verifier_execution.result.status,
                    follow_up=verifier_execution.result.follow_up,
                    extra_details={"checks": failed_checks},
                )

            self.store.append_audit(
                current.run_id,
                "checks_completed",
                payload={"checks": all_checks, "child_run_id": verifier_child.run_id},
            )
            self._record_artifact(
                current.run_id,
                artifact_type="check-report",
                artifact_name="verifier-checks-summary",
                payload={"checks": all_checks, "child_run_id": verifier_child.run_id},
            )
            self._record_checkpoint(
                current.run_id,
                "verification",
                payload={
                    "check_count": len(all_checks),
                    "failed_check_count": len(failed_checks),
                    "child_run_id": verifier_child.run_id,
                },
            )
            self._complete_child_run(
                verifier_child.run_id,
                parent_run_id=current.run_id,
                parent_status=None,
                sync_parent_session=False,
                completion_payload={
                    "relation_type": "agent-verifier",
                    "agent_role": "verifier",
                    "result_status": verifier_execution.result.status,
                    "check_count": len(all_checks),
                },
            )

            current = self._transition(current.run_id, to_status="opening_pr", expected_from="coding")
            commit = provider.commit_and_push(
                preparation.workspace_path,
                branch_name=branch_ref,
                commit_message=self._build_commit_message(current.task_key, context),
            )
            self.store.append_audit(
                current.run_id,
                "branch_pushed",
                payload={"branch_name": commit.branch_name, "commit_sha": commit.commit_sha},
            )
            self._record_artifact(
                current.run_id,
                artifact_type="git-push",
                artifact_name="publish-result",
                payload={"branch_name": commit.branch_name, "commit_sha": commit.commit_sha},
            )
            pr = provider.create_pull_request(
                current.repo_id,
                source_branch=commit.branch_name,
                target_branch=preparation.base_branch,
                title=self._build_pr_title(current.task_key, context),
                description=self._build_pr_description(
                    current,
                    execution,
                    reviewer_summary=reviewer_execution.result.summary,
                    verifier_summary=verifier_execution.result.summary,
                ),
            )
            pr_id = self._extract_pull_request_id(pr)
            pr_url = self._extract_pull_request_url(pr)
            current = self.store.update_run_fields(
                current.run_id,
                pr_id=pr_id,
            )
            self._record_artifact(
                current.run_id,
                artifact_type="pull-request",
                artifact_name="pull-request",
                external_url=pr_url,
                payload={
                    "pr_id": pr_id,
                    "source_branch": commit.branch_name,
                    "target_branch": preparation.base_branch,
                    "url": pr_url,
                },
            )
            current = self._transition(current.run_id, to_status="awaiting_review", expected_from="opening_pr")
            self._record_checkpoint(
                current.run_id,
                "awaiting_review",
                payload={"pr_id": pr_id},
            )
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
                current,
                f"ClawHarness opened PR {pr_id or '-'} from `{commit.branch_name}`.",
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
        parent = self._resolve_root_run(
            self._require_run(
                run_id,
                required_fields=("repo_id", "pr_id", "workspace_path", "branch_name"),
            )
        )
        provider = self._provider_client(parent.provider_type)
        task_context = self._load_task_context(parent.task_id, provider_type=parent.provider_type, repo_id=parent.repo_id)
        all_comments = list(comments or [])
        unresolved_comments = self._collect_unresolved_review_comments(all_comments)
        current = self._create_follow_up_run(parent, relation_type="pr-feedback")
        self._record_artifact(
            current.run_id,
            artifact_type="event",
            artifact_name="pr-feedback-event",
            payload=dict(event_payload or {}),
        )
        self._record_artifact(
            current.run_id,
            artifact_type="review-comments",
            artifact_name="pr-feedback-comments",
            payload={"comments": all_comments, "unresolved_comments": unresolved_comments},
        )

        try:
            current = self._transition(
                current.run_id,
                to_status="planning",
                expected_from=("claimed", "planning"),
            )
            self._record_checkpoint(
                current.run_id,
                "planning",
                payload={
                    "phase": "pr_feedback_loaded",
                    "comment_count": len(all_comments),
                    "unresolved_count": len(unresolved_comments),
                },
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

            current = self._transition(current.run_id, to_status="coding", expected_from=("planning", "coding"))
            self._record_checkpoint(
                current.run_id,
                "coding",
                payload={"phase": "pr_feedback_executor_started", "parent_run_id": parent.run_id},
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
                run_kind="pr-feedback",
                agent_role="executor",
            )
            current = self._persist_executor_session(current, execution, parent_run_id=parent.run_id)
            self.store.append_audit(
                current.run_id,
                "pr_feedback_executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                },
            )
            self._record_checkpoint(
                current.run_id,
                "executor_completed",
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
            self._record_artifact(
                current.run_id,
                artifact_type="check-report",
                artifact_name="pr-feedback-checks",
                payload={"checks": all_checks},
            )
            failed_checks = [item for item in all_checks if self._is_failing_check(item)]
            self._record_checkpoint(
                current.run_id,
                "verification",
                payload={
                    "check_count": len(all_checks),
                    "failed_check_count": len(failed_checks),
                },
            )
            if failed_checks:
                self._block_run(
                    current.run_id,
                    reason="Checks failed while applying PR feedback",
                    details={"checks": failed_checks},
                    parent_run_id=parent.run_id,
                )
                return self.store.get_run(parent.run_id) or parent

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
            self._record_artifact(
                current.run_id,
                artifact_type="git-push",
                artifact_name="pr-feedback-publish",
                payload={
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                    "created_commit": publish.created_commit,
                },
            )

            reply_count = self._reply_to_review_threads(
                provider,
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

            self._complete_child_run(
                current.run_id,
                parent_run_id=parent.run_id,
                parent_status="awaiting_review",
                completion_payload={
                    "relation_type": "pr-feedback",
                    "reply_count": reply_count,
                    "pushed": publish.pushed,
                    "commit_sha": publish.commit_sha,
                },
            )
            parent = self.store.get_run(parent.run_id) or parent
            self._notify(
                event_type="pr_feedback_applied",
                task_key=parent.task_key,
                run_id=parent.run_id,
                summary=f"PR feedback applied for {parent.task_key}",
                details={
                    "pr_id": parent.pr_id,
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                    "child_run_id": current.run_id,
                },
            )
            return self.store.get_run(parent.run_id) or parent
        except Exception as exc:
            self._block_run(
                current.run_id,
                reason=str(exc),
                details={"error_type": type(exc).__name__, "phase": "pr_feedback"},
                parent_run_id=parent.run_id,
            )
            return self.store.get_run(parent.run_id) or parent

    def resume_from_ci_failure(
        self,
        run_id: str,
        *,
        build_summary: Mapping[str, Any] | None = None,
        event_payload: Mapping[str, Any] | None = None,
    ) -> TaskRun:
        parent = self._resolve_root_run(
            self._require_run(
                run_id,
                required_fields=("repo_id", "ci_run_id", "workspace_path", "branch_name"),
            )
        )
        provider = self._provider_client(parent.provider_type)
        task_context = self._load_task_context(parent.task_id, provider_type=parent.provider_type, repo_id=parent.repo_id)
        summary = dict(build_summary or {})
        current = self._create_follow_up_run(parent, relation_type="ci-recovery")
        self._record_artifact(
            current.run_id,
            artifact_type="event",
            artifact_name="ci-recovery-event",
            payload=dict(event_payload or {}),
        )
        self._record_artifact(
            current.run_id,
            artifact_type="ci-summary",
            artifact_name="ci-build-summary",
            payload=summary,
        )

        try:
            current = self._transition(
                current.run_id,
                to_status="planning",
                expected_from=("claimed", "planning"),
            )
            self._record_checkpoint(
                current.run_id,
                "planning",
                payload={
                    "phase": "ci_recovery_loaded",
                    "ci_run_id": current.ci_run_id,
                    "build_result": summary.get("result"),
                },
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

            current = self._transition(
                current.run_id,
                to_status="coding",
                expected_from=("planning", "coding"),
            )
            self._record_checkpoint(
                current.run_id,
                "coding",
                payload={"phase": "ci_recovery_executor_started", "parent_run_id": parent.run_id},
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
                run_kind="ci-recovery",
                agent_role="executor",
            )
            current = self._persist_executor_session(current, execution, parent_run_id=parent.run_id)
            self.store.append_audit(
                current.run_id,
                "ci_recovery_executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                },
            )
            self._record_checkpoint(
                current.run_id,
                "executor_completed",
                payload={
                    "status": execution.result.status,
                    "summary": execution.result.summary,
                    "changed_files": execution.result.changed_files,
                },
            )

            if self._is_human_escalation(execution.result.status):
                self._block_run(
                    current.run_id,
                    reason=execution.result.summary or "CI failure requires human intervention",
                    details={
                        "phase": "ci_recovery",
                        "build_summary": summary,
                        "follow_up": execution.result.follow_up,
                    },
                    parent_run_id=parent.run_id,
                )
                return self.store.get_run(parent.run_id) or parent

            checks = self._run_checks(current.workspace_path or "", execution.result.changed_files)
            all_checks = execution.result.checks + checks
            self.store.append_audit(
                current.run_id,
                "checks_completed",
                payload={"checks": all_checks},
            )
            self._record_artifact(
                current.run_id,
                artifact_type="check-report",
                artifact_name="ci-recovery-checks",
                payload={"checks": all_checks},
            )
            failed_checks = [item for item in all_checks if self._is_failing_check(item)]
            self._record_checkpoint(
                current.run_id,
                "verification",
                payload={
                    "check_count": len(all_checks),
                    "failed_check_count": len(failed_checks),
                },
            )
            if failed_checks:
                self._block_run(
                    current.run_id,
                    reason="Checks failed while recovering CI",
                    details={"checks": failed_checks},
                    parent_run_id=parent.run_id,
                )
                return self.store.get_run(parent.run_id) or parent

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
            self._record_artifact(
                current.run_id,
                artifact_type="git-push",
                artifact_name="ci-recovery-publish",
                payload={
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                    "created_commit": publish.created_commit,
                },
            )

            previous_ci_run_id = current.ci_run_id
            retry_ci_run = getattr(provider, "retry_ci_run", None)
            if callable(retry_ci_run):
                try:
                    retried_build = retry_ci_run(previous_ci_run_id or "", repo_id=current.repo_id)
                except TypeError:
                    retried_build = retry_ci_run(previous_ci_run_id or "")
            else:
                retried_build = provider.retry_build(previous_ci_run_id or "")
            retried_build_id = self._extract_ci_run_id(retried_build, fallback=previous_ci_run_id)
            if retried_build_id is not None:
                current = self.store.update_run_fields(current.run_id, ci_run_id=retried_build_id)
            self.store.append_audit(
                current.run_id,
                "ci_retry_requested",
                payload={
                    "previous_ci_run_id": previous_ci_run_id,
                    "retry_build_id": retried_build_id,
                    "pushed": publish.pushed,
                },
            )
            self._record_artifact(
                current.run_id,
                artifact_type="ci-retry",
                artifact_name="ci-retry-request",
                payload={
                    "previous_ci_run_id": previous_ci_run_id,
                    "retry_build_id": retried_build_id,
                    "pushed": publish.pushed,
                },
            )

            self._complete_child_run(
                current.run_id,
                parent_run_id=parent.run_id,
                parent_status="awaiting_ci",
                parent_ci_run_id=retried_build_id,
                completion_payload={
                    "relation_type": "ci-recovery",
                    "previous_ci_run_id": previous_ci_run_id,
                    "retry_build_id": retried_build_id,
                },
            )
            parent = self.store.get_run(parent.run_id) or parent
            self._notify(
                event_type="ci_recovery_started",
                task_key=parent.task_key,
                run_id=parent.run_id,
                summary=f"CI recovery pushed for {parent.task_key}",
                details={
                    "ci_run_id": parent.ci_run_id,
                    "branch_name": publish.branch_name,
                    "commit_sha": publish.commit_sha,
                    "pushed": publish.pushed,
                    "child_run_id": current.run_id,
                },
            )
            return self.store.get_run(parent.run_id) or parent
        except Exception as exc:
            self._block_run(
                current.run_id,
                reason=str(exc),
                details={"error_type": type(exc).__name__, "phase": "ci_recovery"},
                parent_run_id=parent.run_id,
            )
            return self.store.get_run(parent.run_id) or parent

    def _run_executor(self, run: TaskRun, task_context: Mapping[str, Any]) -> ExecutorRunOutcome:
        result_path = self._executor_result_path(run.run_id, "executor-result.json")
        return self._run_executor_request(
            run,
            task_context=task_context,
            result_path=result_path,
            task_prompt=self._build_executor_prompt(run, run, task_context, result_path, None),
            constraints=[
                "Use existing repository patterns.",
                "Run relevant local checks before finishing.",
                "Do not push or open the PR directly; the harness owns release actions.",
            ],
        )

    def _run_child_agent(
        self,
        parent_run: TaskRun,
        *,
        task_context: Mapping[str, Any],
        agent_role: str,
        artifact_name: str,
        task_prompt_builder: Callable[[TaskRun, Path], str],
        constraints: list[str],
        stage: str,
        run_kind: str = "task",
        extra_artifacts: Mapping[str, Any] | None = None,
    ) -> tuple[TaskRun | None, ExecutorRunOutcome | None]:
        relation_type = f"agent-{agent_role}"
        child = self._create_follow_up_run(parent_run, relation_type=relation_type)
        try:
            child = self._transition(child.run_id, to_status="planning", expected_from=("claimed", "planning"))
            self._record_checkpoint(
                child.run_id,
                "planning",
                payload={
                    "phase": f"{agent_role}_loaded",
                    "agent_role": agent_role,
                    "relation_type": relation_type,
                    "parent_run_id": parent_run.run_id,
                },
            )
            self.store.append_audit(
                child.run_id,
                "agent_started",
                payload={
                    "agent_role": agent_role,
                    "relation_type": relation_type,
                    "parent_run_id": parent_run.run_id,
                    "stage": stage,
                },
            )
            skill_selection = self._record_skill_selection(
                child.run_id,
                parent_run_id=parent_run.run_id,
                run_kind=run_kind,
                agent_role=agent_role,
                provider_type=parent_run.provider_type,
                task_context=task_context,
            )
            if stage != "planning":
                child = self._transition(child.run_id, to_status="coding", expected_from=("planning", "coding"))
                self._record_checkpoint(
                    child.run_id,
                    stage,
                    payload={
                        "phase": f"{agent_role}_started",
                        "agent_role": agent_role,
                        "relation_type": relation_type,
                        "parent_run_id": parent_run.run_id,
                    },
                )

            result_path = self._executor_result_path(child.run_id, artifact_name)
            task_prompt = self._apply_skill_selection_to_prompt(
                task_prompt_builder(child, result_path),
                skill_selection,
            )
            execution = self._run_executor_request(
                child,
                task_context=task_context,
                result_path=result_path,
                task_prompt=task_prompt,
                constraints=constraints,
                skill_selection=skill_selection,
                extra_artifacts=extra_artifacts,
                use_default_label=False,
            )
            child = self._persist_executor_session(child, execution)
            self._record_agent_result(parent_run.run_id, child, agent_role=agent_role, relation_type=relation_type, execution=execution)
            return child, execution
        except Exception as exc:
            self._record_agent_remediation(
                parent_run_id=parent_run.run_id,
                child_run_id=child.run_id,
                agent_role=agent_role,
                relation_type=relation_type,
                decision="awaiting_human",
                reason=str(exc),
                result_status="error",
                follow_up=[],
            )
            self._block_run(
                child.run_id,
                reason=str(exc),
                details={
                    "agent_role": agent_role,
                    "relation_type": relation_type,
                    "error_type": type(exc).__name__,
                    "decision": "awaiting_human",
                },
                parent_run_id=parent_run.run_id,
            )
            return None, None

    def _run_resume_executor(
        self,
        run: TaskRun,
        *,
        task_context: Mapping[str, Any],
        artifact_name: str,
        task_prompt: str,
        constraints: list[str],
        run_kind: str,
        agent_role: str,
        extra_artifacts: Mapping[str, Any] | None = None,
    ) -> ExecutorRunOutcome:
        result_path = self._executor_result_path(run.run_id, artifact_name)
        parent = self.store.get_parent_run(run.run_id)
        skill_selection = self._record_skill_selection(
            run.run_id,
            parent_run_id=parent.run_id if parent is not None else None,
            run_kind=run_kind,
            agent_role=agent_role,
            provider_type=run.provider_type,
            task_context=task_context,
        )
        return self._run_executor_request(
            run,
            task_context=task_context,
            result_path=result_path,
            task_prompt=self._apply_skill_selection_to_prompt(task_prompt, skill_selection),
            constraints=constraints,
            skill_selection=skill_selection,
            extra_artifacts=extra_artifacts,
            resume_session_id=run.session_id,
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
        skill_selection: SkillSelection | None = None,
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
        if skill_selection is not None:
            artifacts["skill_selection"] = skill_selection.to_payload()

        request = ExecutorRequest(
            workspace_path=str(workspace),
            task_prompt=task_prompt,
            constraints=constraints,
            artifacts=artifacts,
            label=run.task_key if use_default_label else None,
            mode="run",
            thread=False,
        )
        outcome = self.executor_runner.run_and_wait(
            request,
            result_path=result_path,
            timeout_seconds=self.config.executor.timeout_seconds,
            poll_interval_seconds=1.0,
            resume_session_id=resume_session_id,
        )
        self._record_artifact(
            run.run_id,
            artifact_type="executor-result",
            artifact_name=result_path.name,
            path=str(result_path),
            payload={
                "status": outcome.result.status,
                "summary": outcome.result.summary,
                "changed_files": outcome.result.changed_files,
                "checks": outcome.result.checks,
                "follow_up": outcome.result.follow_up,
                "session_id": outcome.spawn.session_id,
            },
        )
        return outcome

    def _record_agent_result(
        self,
        parent_run_id: str,
        child_run: TaskRun,
        *,
        agent_role: str,
        relation_type: str,
        execution: ExecutorRunOutcome,
    ) -> None:
        payload = {
            "child_run_id": child_run.run_id,
            "agent_role": agent_role,
            "relation_type": relation_type,
            "status": execution.result.status,
            "summary": execution.result.summary,
            "changed_files": execution.result.changed_files,
            "follow_up": execution.result.follow_up,
            "session_id": execution.spawn.session_id,
        }
        self.store.append_audit(
            child_run.run_id,
            "agent_completed",
            payload=payload,
        )
        self._record_checkpoint(
            child_run.run_id,
            "agent_completed",
            payload=payload,
        )
        self.store.append_audit(
            parent_run_id,
            "agent_result_recorded",
            payload=payload,
        )

    def _record_agent_remediation(
        self,
        *,
        parent_run_id: str,
        child_run_id: str,
        agent_role: str,
        relation_type: str,
        decision: str,
        reason: str,
        result_status: str,
        follow_up: list[str],
        extra_details: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "child_run_id": child_run_id,
            "agent_role": agent_role,
            "relation_type": relation_type,
            "decision": decision,
            "reason": reason,
            "result_status": result_status,
            "follow_up": follow_up,
        }
        if extra_details:
            payload.update(dict(extra_details))
        self.store.append_audit(parent_run_id, "agent_remediation_recorded", payload=payload)
        self.store.append_audit(child_run_id, "agent_remediation_recorded", payload=payload)
        self._record_checkpoint(child_run_id, "agent_decision", payload=payload)

    def _block_agent_child(
        self,
        parent_run: TaskRun,
        child_run: TaskRun,
        *,
        agent_role: str,
        relation_type: str,
        reason: str,
        result_status: str,
        follow_up: list[str],
        extra_details: Mapping[str, Any] | None = None,
    ) -> TaskRun:
        self._record_agent_remediation(
            parent_run_id=parent_run.run_id,
            child_run_id=child_run.run_id,
            agent_role=agent_role,
            relation_type=relation_type,
            decision="awaiting_human",
            reason=reason,
            result_status=result_status,
            follow_up=follow_up,
            extra_details=extra_details,
        )
        self._block_run(
            child_run.run_id,
            reason=reason,
            details={
                "agent_role": agent_role,
                "relation_type": relation_type,
                "result_status": result_status,
                "follow_up": follow_up,
                **(dict(extra_details) if extra_details else {}),
            },
            parent_run_id=parent_run.run_id,
        )
        return self.store.get_run(parent_run.run_id) or parent_run

    def _promote_child_session(
        self,
        parent_run: TaskRun,
        *,
        child_run: TaskRun,
        session_id: str | None,
        agent_role: str,
    ) -> TaskRun:
        if not session_id or session_id == parent_run.session_id:
            return self.store.get_run(parent_run.run_id) or parent_run

        updated = self.store.update_run_fields(parent_run.run_id, session_id=session_id)
        self.store.append_audit(
            parent_run.run_id,
            "executor_session_updated",
            payload={
                "previous_session_id": parent_run.session_id,
                "session_id": session_id,
                "child_run_id": child_run.run_id,
                "agent_role": agent_role,
            },
        )
        return updated

    def _executor_result_path(self, run_id: str, artifact_name: str) -> Path:
        artifact_dir = Path(self.config.runtime.workspace_root) / ".executor-artifacts" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return artifact_dir / artifact_name

    def _persist_executor_session(
        self,
        run: TaskRun,
        execution: ExecutorRunOutcome,
        *,
        parent_run_id: str | None = None,
    ) -> TaskRun:
        session_id = execution.spawn.session_id
        if not session_id or session_id == run.session_id:
            return self.store.get_run(run.run_id) or run

        updated = self.store.update_run_fields(run.run_id, session_id=session_id)
        self.store.append_audit(
            run.run_id,
            "executor_session_updated",
            payload={"previous_session_id": run.session_id, "session_id": session_id},
        )
        if parent_run_id and parent_run_id != run.run_id:
            self.store.update_run_fields(parent_run_id, session_id=session_id)
            self.store.append_audit(
                parent_run_id,
                "child_executor_session_updated",
                payload={
                    "child_run_id": run.run_id,
                    "previous_session_id": run.session_id,
                    "session_id": session_id,
                },
            )
        return updated

    def _is_success_status(self, status: str, *, allowed: set[str] | None = None) -> bool:
        normalized = status.strip().lower()
        accepted = allowed or {"completed", "success"}
        return normalized in {item.strip().lower() for item in accepted}

    def _require_run(self, run_id: str, *, required_fields: tuple[str, ...] = ()) -> TaskRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise TaskOrchestratorError(f"Run not found: {run_id}")

        missing = [field for field in required_fields if not getattr(run, field)]
        if missing:
            raise TaskOrchestratorError(f"Run {run_id} is missing required fields: {', '.join(missing)}")
        return run

    def _resolve_root_run(self, run: TaskRun) -> TaskRun:
        current = run
        visited = {run.run_id}
        while True:
            parent = self.store.get_parent_run(current.run_id)
            if parent is None or parent.run_id in visited:
                return current
            visited.add(parent.run_id)
            current = parent

    def _create_follow_up_run(self, parent_run: TaskRun, *, relation_type: str) -> TaskRun:
        agent_role = self._agent_role_from_relation_type(relation_type)
        child = self.store.create_run(
            TaskRun(
                run_id=self._child_run_id(parent_run.run_id, relation_type),
                provider_type=parent_run.provider_type,
                task_id=parent_run.task_id,
                task_key=parent_run.task_key,
                repo_id=parent_run.repo_id,
                branch_name=parent_run.branch_name,
                workspace_path=parent_run.workspace_path,
                pr_id=parent_run.pr_id,
                ci_run_id=parent_run.ci_run_id,
                chat_thread_id=parent_run.chat_thread_id,
                session_id=parent_run.session_id,
                executor_type=parent_run.executor_type,
                status="claimed",
            )
        )
        self.store.link_runs(parent_run.run_id, child.run_id, relation_type=relation_type)
        self.store.append_audit(
            parent_run.run_id,
            "child_run_created",
            payload={
                "child_run_id": child.run_id,
                "relation_type": relation_type,
                "agent_role": agent_role,
                "status": child.status,
            },
        )
        self._record_checkpoint(
            child.run_id,
            "claimed",
            payload={
                "parent_run_id": parent_run.run_id,
                "relation_type": relation_type,
                "agent_role": agent_role,
            },
        )
        return child

    def _child_run_id(self, parent_run_id: str, relation_type: str) -> str:
        suffix = uuid.uuid4().hex[:8]
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", relation_type).strip("-") or "child"
        return f"{parent_run_id}--{slug}--{suffix}"

    def _sync_parent_run(
        self,
        parent_run_id: str,
        *,
        status: str | None = None,
        ci_run_id: str | None = None,
        session_id: str | None = None,
        last_error: str | None = None,
    ) -> TaskRun:
        parent = self._require_run(parent_run_id)
        if ci_run_id is not None or session_id is not None:
            parent = self.store.update_run_fields(
                parent_run_id,
                ci_run_id=ci_run_id,
                session_id=session_id,
            )
        if status is not None:
            try:
                parent = self.store.transition_status(
                    parent_run_id,
                    to_status=status,
                    expected_from=(
                        "claimed",
                        "planning",
                        "coding",
                        "opening_pr",
                        "awaiting_ci",
                        "awaiting_review",
                        "awaiting_human",
                        status,
                    ),
                    last_error=last_error,
                )
            except StatusTransitionError:
                parent = self._require_run(parent_run_id)
            self._record_checkpoint(
                parent.run_id,
                status,
                payload={"phase": "parent_sync", "status": status},
            )
        return self.store.get_run(parent_run_id) or parent

    def _complete_child_run(
        self,
        run_id: str,
        *,
        parent_run_id: str,
        parent_status: str | None,
        parent_ci_run_id: str | None = None,
        completion_payload: dict[str, Any] | None = None,
        sync_parent_session: bool = True,
    ) -> TaskRun:
        completed = self._transition(
            run_id,
            to_status="completed",
            expected_from=("claimed", "planning", "coding", "opening_pr", "awaiting_ci", "awaiting_review", "completed"),
        )
        self._record_checkpoint(completed.run_id, "completed", payload=completion_payload)
        parent = self._sync_parent_run(
            parent_run_id,
            status=parent_status,
            ci_run_id=parent_ci_run_id,
            session_id=completed.session_id if sync_parent_session else None,
        )
        self.store.append_audit(
            parent.run_id,
            "child_run_completed",
            payload={
                "child_run_id": completed.run_id,
                "child_status": completed.status,
                "parent_status": parent.status,
                **(completion_payload or {}),
            },
        )
        return completed

    def _agent_role_from_relation_type(self, relation_type: str) -> str | None:
        if relation_type.startswith("agent-"):
            role = relation_type.removeprefix("agent-").strip()
            return role or None
        return None

    def _record_checkpoint(self, run_id: str, stage: str, *, payload: dict[str, Any] | None = None) -> None:
        self.store.record_checkpoint(run_id, stage, payload=payload)

    def _record_artifact(
        self,
        run_id: str,
        *,
        artifact_type: str,
        artifact_name: str,
        path: str | None = None,
        external_url: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.store.record_artifact(
            run_id,
            artifact_type,
            artifact_name,
            path=path,
            external_url=external_url,
            payload=payload,
        )

    def _record_skill_selection(
        self,
        run_id: str,
        *,
        parent_run_id: str | None,
        run_kind: str,
        agent_role: str,
        provider_type: str,
        task_context: Mapping[str, Any],
    ) -> SkillSelection:
        selection = self.skill_registry.select(
            run_kind=run_kind,
            agent_role=agent_role,
            provider_type=provider_type,
            task_context=task_context,
        )
        payload = selection.to_payload()
        selection_key = f"{run_kind}:{agent_role}:{provider_type}"
        self.store.record_skill_selection(
            run_id,
            parent_run_id=parent_run_id,
            run_kind=run_kind,
            agent_role=agent_role,
            registry_version=selection.registry_version,
            selection_key=selection_key,
            payload=payload,
        )
        event_type = "skill_selection_fallback" if selection.used_safe_default else "skill_selection_applied"
        self.store.append_audit(
            run_id,
            event_type,
            payload={
                "selection_key": selection_key,
                "run_kind": run_kind,
                "agent_role": agent_role,
                "provider_type": provider_type,
                "registry_version": selection.registry_version,
                "matched_skill_ids": [skill.skill_id for skill in selection.matched_skills],
                "fallback_reason": selection.fallback_reason,
            },
        )
        return selection

    def _apply_skill_selection_to_prompt(self, prompt: str, selection: SkillSelection) -> str:
        lines = [prompt, "", "ClawHarness selected skills:"]
        if selection.matched_skills:
            for skill in selection.matched_skills:
                lines.append(f"- {skill.skill_id} v{skill.version} ({skill.source})")
                lines.append(f"  Purpose: {skill.description}")
                for instruction in skill.instructions:
                    lines.append(f"  Guidance: {instruction}")
        else:
            lines.append("- No specialized skill matched.")
            lines.append("  Guidance: Use the safe default path, follow repository conventions, and obey the explicit task constraints.")
        lines.append("")
        lines.append(f"Selection reason: {selection.selection_reason}")
        if selection.fallback_reason:
            lines.append(f"Fallback reason: {selection.fallback_reason}")
        return "\n".join(lines)

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
            provider = self._provider_client(run.provider_type)
            commit = provider.commit_and_push(
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
        except ProviderApiError as exc:
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
        provider_label = self._provider_label(run.provider_type)
        return "\n".join(
            [
                f"Resume run `{run.run_id}` for PR feedback on {provider_label} task `{run.task_key}`.",
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
        provider_label = self._provider_label(run.provider_type)
        return "\n".join(
            [
                f"Resume run `{run.run_id}` for CI recovery on {provider_label} task `{run.task_key}`.",
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
        provider: WorkflowProviderClient,
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
            provider.reply_to_pull_request(
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
        commands: list[CheckCommand] = [
            CheckCommand(
                name="git diff --check",
                argv=["git", "-c", "core.whitespace=cr-at-eol", "diff", "--check"],
            )
        ]
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

    def _build_planner_prompt(
        self,
        parent_run: TaskRun,
        child_run: TaskRun,
        task_context: Mapping[str, Any],
        result_path: Path,
    ) -> str:
        provider_label = self._provider_label(parent_run.provider_type)
        return "\n".join(
            [
                f"Plan {provider_label} task `{parent_run.task_key}` for ClawHarness.",
                f"Parent run: {parent_run.run_id}",
                f"Planner child run: {child_run.run_id}",
                f"Workspace: {child_run.workspace_path}",
                "",
                "Required workflow:",
                "1. Analyze the task context and current workspace readiness.",
                "2. Produce a concise implementation plan, validation strategy, and key risks.",
                '3. Write a structured result where status is "completed" only if execution can proceed safely.',
                '4. Use status "needs_human" when the task is too ambiguous or risky to continue automatically.',
                "5. Do not modify files, commit, push, or open PRs.",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
                "",
                f"Result artifact: {result_path}",
            ]
        )

    def _build_executor_prompt(
        self,
        parent_run: TaskRun,
        child_run: TaskRun,
        task_context: Mapping[str, Any],
        result_path: Path,
        planner_result: ExecutorResult | None,
    ) -> str:
        provider_label = self._provider_label(parent_run.provider_type)
        planner_payload = {
            "summary": planner_result.summary if planner_result is not None else "",
            "follow_up": planner_result.follow_up if planner_result is not None else [],
        }
        return "\n".join(
            [
                f"Implement {provider_label} task `{parent_run.task_key}`.",
                f"Parent run: {parent_run.run_id}",
                f"Executor child run: {child_run.run_id}",
                f"Workspace: {child_run.workspace_path}",
                "",
                "Required workflow:",
                "1. Implement the planned changes in the workspace.",
                "2. Run relevant local checks before finishing.",
                "3. Summarize changed files, validation notes, and remaining follow-up.",
                "4. Write the structured result JSON to the provided artifact path.",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
                "",
                "Planner result:",
                "```json",
                json.dumps(planner_payload, indent=2, sort_keys=True),
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

    def _build_reviewer_prompt(
        self,
        parent_run: TaskRun,
        child_run: TaskRun,
        task_context: Mapping[str, Any],
        result_path: Path,
        executor_result: ExecutorResult,
    ) -> str:
        provider_label = self._provider_label(parent_run.provider_type)
        return "\n".join(
            [
                f"Review the current workspace for {provider_label} task `{parent_run.task_key}`.",
                f"Parent run: {parent_run.run_id}",
                f"Reviewer child run: {child_run.run_id}",
                f"Workspace: {child_run.workspace_path}",
                "",
                "Required workflow:",
                "1. Review the workspace against the task intent and implementation summary.",
                '2. Use status "approved" or "completed" only when the change is ready for verification.',
                '3. Use status "needs_human" when blocking issues remain and list the follow-up explicitly.',
                "4. Do not modify files, commit, push, or open PRs.",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
                "",
                "Executor result:",
                "```json",
                json.dumps(
                    {
                        "status": executor_result.status,
                        "summary": executor_result.summary,
                        "changed_files": executor_result.changed_files,
                        "follow_up": executor_result.follow_up,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                "```",
                "",
                f"Result artifact: {result_path}",
            ]
        )

    def _build_verifier_prompt(
        self,
        parent_run: TaskRun,
        child_run: TaskRun,
        task_context: Mapping[str, Any],
        result_path: Path,
        planner_result: ExecutorResult,
        executor_result: ExecutorResult,
        reviewer_result: ExecutorResult,
    ) -> str:
        provider_label = self._provider_label(parent_run.provider_type)
        return "\n".join(
            [
                f"Verify PR readiness for {provider_label} task `{parent_run.task_key}`.",
                f"Parent run: {parent_run.run_id}",
                f"Verifier child run: {child_run.run_id}",
                f"Workspace: {child_run.workspace_path}",
                "",
                "Required workflow:",
                "1. Verify the current workspace against the task context and upstream agent conclusions.",
                '2. Use status "completed", "passed", or "ready" only when the change is ready for PR creation.',
                '3. Use status "needs_human" when the task is not publish-ready, and explain the blocking point.',
                "4. Do not modify files, commit, push, or open PRs.",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
                "",
                "Agent summaries:",
                "```json",
                json.dumps(
                    {
                        "planner": {
                            "status": planner_result.status,
                            "summary": planner_result.summary,
                            "follow_up": planner_result.follow_up,
                        },
                        "executor": {
                            "status": executor_result.status,
                            "summary": executor_result.summary,
                            "changed_files": executor_result.changed_files,
                            "follow_up": executor_result.follow_up,
                        },
                        "reviewer": {
                            "status": reviewer_result.status,
                            "summary": reviewer_result.summary,
                            "follow_up": reviewer_result.follow_up,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                "```",
                "",
                f"Result artifact: {result_path}",
            ]
        )

    def _build_pr_description(
        self,
        run: TaskRun,
        execution: ExecutorRunOutcome,
        *,
        reviewer_summary: str | None = None,
        verifier_summary: str | None = None,
    ) -> str:
        lines = [
            f"Automated change for `{run.task_key}`.",
            "",
            execution.result.summary or "No summary provided.",
        ]
        if reviewer_summary:
            lines.extend(["", "Review summary:", reviewer_summary])
        if verifier_summary:
            lines.extend(["", "Verification summary:", verifier_summary])
        if execution.result.follow_up:
            lines.extend(["", "Follow-up:", *[f"- {item}" for item in execution.result.follow_up]])
        return "\n".join(lines)

    def _load_task_context(
        self,
        task_id: str,
        *,
        provider_type: str,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        provider = self._provider_client(provider_type)
        fields = [
            "System.Title",
            "System.Description",
            "System.State",
            "System.TeamProject",
            "System.AssignedTo",
        ]
        try:
            return provider.get_task(task_id, repo_id=repo_id, fields=fields)
        except TypeError:
            return provider.get_task(task_id, fields=fields)

    def _extract_pull_request_id(self, payload: Mapping[str, Any]) -> str | None:
        for key in ("pullRequestId", "number", "id"):
            value = payload.get(key)
            if value is not None:
                return str(value)
        return None

    def _extract_pull_request_url(self, payload: Mapping[str, Any]) -> str | None:
        for key in ("url", "html_url"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        links = payload.get("_links")
        if isinstance(links, Mapping):
            web = links.get("web")
            if isinstance(web, Mapping):
                href = web.get("href")
                if isinstance(href, str) and href:
                    return href
        return None

    def _extract_ci_run_id(self, payload: Mapping[str, Any], *, fallback: str | None = None) -> str | None:
        value = payload.get("id")
        if value is None:
            return fallback
        if isinstance(value, str) and ":" in value:
            return value
        return str(value)

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

    def _block_run(
        self,
        run_id: str,
        *,
        reason: str,
        details: dict[str, Any],
        parent_run_id: str | None = None,
    ) -> TaskRun:
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
        self._record_checkpoint(
            run_id,
            "awaiting_human",
            payload={"reason": reason, **details},
        )
        if parent_run_id and parent_run_id != run_id:
            parent = self._sync_parent_run(
                parent_run_id,
                status="awaiting_human",
                session_id=blocked.session_id,
                last_error=reason,
            )
            self.store.append_audit(
                parent.run_id,
                "child_run_blocked",
                payload={"child_run_id": run_id, "reason": reason, **details},
            )
        self._notify(
            event_type="task_blocked",
            task_key=blocked.task_key,
            run_id=parent_run_id or blocked.run_id,
            summary=f"Run {blocked.task_key} blocked",
            details={"reason": reason, "child_run_id": run_id if parent_run_id else None, **details},
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

    def _safe_add_task_comment(self, run: TaskRun, text: str) -> None:
        provider = self._provider_client(run.provider_type)
        try:
            try:
                provider.add_task_comment(run.task_id, text, repo_id=run.repo_id)
            except TypeError:
                provider.add_task_comment(run.task_id, text)
        except ProviderApiError:
            return

    def _provider_client(self, provider_type: str) -> WorkflowProviderClient:
        provider = self.provider_clients.get(provider_type)
        if provider is None:
            raise TaskOrchestratorError(f"Provider client not configured: {provider_type}")
        return provider

    def _provider_label(self, provider_type: str) -> str:
        provider = self._provider_client(provider_type)
        label = getattr(provider, "display_name", None)
        if isinstance(label, str) and label:
            return label
        return provider_type

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
