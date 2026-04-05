from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ado_client import AzureDevOpsRestClient, NormalizedAdoEvent
from rocketchat_notifier import RocketChatNotifier, RocketChatNotifierError
from run_store import ClaimRequest, RunStore, StatusTransitionError, TaskRun

from .config import HarnessRuntimeConfig
from .openclaw_client import OpenClawWebhookClient
from .orchestrator import TaskRunOrchestrator


RunIdFactory = Callable[[], str]


@dataclass(frozen=True)
class BridgeResult:
    accepted: bool
    action: str
    run_id: str | None = None
    reason: str | None = None
    session_key: str | None = None


class HarnessBridge:
    def __init__(
        self,
        *,
        config: HarnessRuntimeConfig,
        store: RunStore,
        ado_client: AzureDevOpsRestClient,
        openclaw_client: OpenClawWebhookClient,
        notifier: RocketChatNotifier | None = None,
        task_orchestrator: TaskRunOrchestrator | None = None,
        run_id_factory: RunIdFactory | None = None,
    ):
        self.config = config
        self.store = store
        self.ado_client = ado_client
        self.openclaw_client = openclaw_client
        self.notifier = notifier
        self.task_orchestrator = task_orchestrator
        self.run_id_factory = run_id_factory or (lambda: str(uuid.uuid4()))

    def handle_ado_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> BridgeResult:
        normalized = self.ado_client.normalize_event(event_type=event_type, payload=payload, source_id=source_id)

        if normalized.task_id and event_type.startswith("task."):
            return self._handle_task_event(normalized)
        if normalized.pr_id and event_type.startswith("pr."):
            return self._handle_pr_event(normalized)
        if normalized.ci_run_id and event_type.startswith("ci."):
            return self._handle_ci_event(normalized)
        return BridgeResult(accepted=False, action="ignored", reason="unsupported_event")

    def _handle_task_event(self, normalized: NormalizedAdoEvent) -> BridgeResult:
        task_key = normalized.task_key or normalized.task_id or "unknown-task"
        run_id = self.run_id_factory()
        session_key = self._session_key("task", task_key)
        run = TaskRun(
            run_id=run_id,
            provider_type="azure-devops",
            task_id=normalized.task_id or "unknown",
            task_key=task_key,
            session_id=session_key,
            executor_type=self.config.executor.mode,
            status="claimed",
            repo_id=normalized.repo_id,
        )
        claim = self.store.claim_run(
            ClaimRequest(
                fingerprint=self._fingerprint(normalized),
                source_type=normalized.event_type,
                source_id=normalized.source_id,
                owner=self.config.owner,
                dedupe_ttl_seconds=self.config.runtime.dedupe_ttl_seconds,
                lock_ttl_seconds=self.config.runtime.lock_ttl_seconds,
                run=run,
            )
        )
        if not claim.accepted:
            return BridgeResult(
                accepted=False,
                action="task_claim_rejected",
                run_id=claim.existing_run.run_id if claim.existing_run else None,
                reason=claim.reason,
                session_key=claim.existing_run.session_id if claim.existing_run else None,
            )

        task_context = self._load_task_context(normalized.task_id)
        prompt = self._build_task_prompt(normalized, claim.run.run_id, task_context)
        self.store.transition_status(
            claim.run.run_id,
            to_status="planning",
            expected_from="claimed",
        )
        if self.task_orchestrator is None:
            self.openclaw_client.run_agent(
                message=prompt,
                name="Azure DevOps Task",
                agent_id=self.config.openclaw_hooks.agent_id,
                session_key=session_key,
                wake_mode=self.config.openclaw_hooks.wake_mode,
                deliver=False,
                timeout_seconds=self.config.executor.timeout_seconds,
            )
            self.store.append_audit(
                claim.run.run_id,
                "openclaw_dispatch",
                payload={"event_type": normalized.event_type, "session_key": session_key},
            )
        else:
            self.store.append_audit(
                claim.run.run_id,
                "task_run_queued",
                payload={"event_type": normalized.event_type, "session_key": session_key},
            )
            threading.Thread(
                target=self._run_task_orchestration,
                args=(claim.run.run_id, task_context),
                daemon=True,
            ).start()
        self._notify(
            event_type="task_started",
            task_key=task_key,
            run_id=claim.run.run_id,
            summary=f"Task {task_key} claimed and dispatched to OpenClaw",
            details={"event_type": normalized.event_type},
        )
        return BridgeResult(
            accepted=True,
            action="task_dispatched",
            run_id=claim.run.run_id,
            session_key=session_key,
        )

    def _handle_pr_event(self, normalized: NormalizedAdoEvent) -> BridgeResult:
        run = self.store.find_run_by_pr_id(normalized.pr_id or "")
        if run is None:
            return BridgeResult(accepted=False, action="pr_resume_skipped", reason="run_not_found")

        comments = []
        if normalized.repo_id:
            comments = self.ado_client.list_pull_request_comments(normalized.repo_id, normalized.pr_id or "")
        prompt = self._build_pr_prompt(normalized, run.run_id, comments)
        self.openclaw_client.run_agent(
            message=prompt,
            name="Azure DevOps PR Feedback",
            agent_id=self.config.openclaw_hooks.agent_id,
            session_key=run.session_id,
            wake_mode=self.config.openclaw_hooks.wake_mode,
            deliver=False,
            timeout_seconds=self.config.executor.timeout_seconds,
        )
        self._safe_transition(run.run_id, to_status="coding", expected_from=("awaiting_review", "awaiting_ci", "planning"))
        self.store.append_audit(
            run.run_id,
            "pr_feedback_dispatch",
            payload={"pr_id": normalized.pr_id, "event_type": normalized.event_type},
        )
        return BridgeResult(accepted=True, action="pr_feedback_dispatched", run_id=run.run_id, session_key=run.session_id)

    def _handle_ci_event(self, normalized: NormalizedAdoEvent) -> BridgeResult:
        run = self.store.find_run_by_ci_run_id(normalized.ci_run_id or "")
        if run is None:
            return BridgeResult(accepted=False, action="ci_resume_skipped", reason="run_not_found")

        build_summary = self.ado_client.get_build(normalized.ci_run_id or "")
        prompt = self._build_ci_prompt(normalized, run.run_id, build_summary)
        self.openclaw_client.run_agent(
            message=prompt,
            name="Azure DevOps CI Failure",
            agent_id=self.config.openclaw_hooks.agent_id,
            session_key=run.session_id,
            wake_mode=self.config.openclaw_hooks.wake_mode,
            deliver=False,
            timeout_seconds=self.config.executor.timeout_seconds,
        )
        self._safe_transition(run.run_id, to_status="coding", expected_from=("awaiting_ci", "awaiting_review", "planning"))
        self.store.append_audit(
            run.run_id,
            "ci_recovery_dispatch",
            payload={"ci_run_id": normalized.ci_run_id, "event_type": normalized.event_type},
        )
        self._notify(
            event_type="ci_failed",
            task_key=run.task_key,
            run_id=run.run_id,
            summary=f"CI failure for {run.task_key} dispatched to OpenClaw",
            details={"ci_run_id": normalized.ci_run_id},
        )
        return BridgeResult(accepted=True, action="ci_recovery_dispatched", run_id=run.run_id, session_key=run.session_id)

    def _load_task_context(self, task_id: str | None) -> dict[str, Any]:
        if not task_id:
            return {}
        try:
            return self.ado_client.get_task(
                task_id,
                fields=[
                    "System.Title",
                    "System.Description",
                    "System.State",
                    "System.TeamProject",
                    "System.AssignedTo",
                ],
                expand="relations",
            )
        except Exception as exc:
            return {"task_fetch_error": str(exc), "task_id": task_id}

    def _build_task_prompt(self, normalized: NormalizedAdoEvent, run_id: str, task_context: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"Handle Azure DevOps task event `{normalized.event_type}`.",
                f"Run id: {run_id}",
                f"Task key: {normalized.task_key}",
                f"Task id: {normalized.task_id}",
                "",
                "Required workflow:",
                "1. analyze-task",
                "2. implement-task",
                "3. prepare workspace",
                "4. run checks before push",
                "5. open PR",
                "",
                "Task context:",
                "```json",
                json.dumps(task_context, indent=2, sort_keys=True),
                "```",
            ]
        )

    def _build_pr_prompt(self, normalized: NormalizedAdoEvent, run_id: str, comments: list[dict[str, Any]]) -> str:
        return "\n".join(
            [
                f"Resume run `{run_id}` for PR feedback.",
                f"Event type: {normalized.event_type}",
                f"PR id: {normalized.pr_id}",
                "",
                "Run fix-pr-feedback, patch the branch, rerun checks, and update the PR.",
                "",
                "Comments:",
                "```json",
                json.dumps(comments, indent=2, sort_keys=True),
                "```",
            ]
        )

    def _build_ci_prompt(self, normalized: NormalizedAdoEvent, run_id: str, build_summary: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"Resume run `{run_id}` for CI recovery.",
                f"Event type: {normalized.event_type}",
                f"CI run id: {normalized.ci_run_id}",
                "",
                "Run recover-ci-failure, patch if possible, rerun checks, and escalate to awaiting_human if not recoverable.",
                "",
                "Build summary:",
                "```json",
                json.dumps(build_summary, indent=2, sort_keys=True),
                "```",
            ]
        )

    def _fingerprint(self, normalized: NormalizedAdoEvent) -> str:
        if normalized.source_id:
            return f"ado:{normalized.event_type}:{normalized.source_id}"
        stable = json.dumps(normalized.to_dict(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        return f"ado:{normalized.event_type}:{digest}"

    def _session_key(self, prefix: str, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._:-]+", "-", value).strip("-") or "unknown"
        return f"{self.config.openclaw_hooks.default_session_key}:{prefix}:{slug}"

    def _safe_transition(self, run_id: str, *, to_status: str, expected_from: tuple[str, ...]) -> None:
        try:
            self.store.transition_status(run_id, to_status=to_status, expected_from=expected_from)
        except StatusTransitionError:
            self.store.append_audit(
                run_id,
                "status_transition_skipped",
                payload={"to_status": to_status, "expected_from": list(expected_from)},
            )

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
        except RocketChatNotifierError as exc:
            self.store.append_audit(
                run_id,
                "notification_failed",
                payload={
                    "provider": "rocketchat",
                    "event_type": event_type,
                    "error": str(exc),
                },
            )

    def _run_task_orchestration(self, run_id: str, task_context: Mapping[str, Any]) -> None:
        if self.task_orchestrator is None:
            return
        try:
            self.task_orchestrator.run_claimed_task(run_id, task_context=task_context)
        except Exception as exc:
            self.store.append_audit(
                run_id,
                "task_run_failed",
                payload={"error": str(exc), "error_type": type(exc).__name__},
            )
