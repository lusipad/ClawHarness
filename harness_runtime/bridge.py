from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ado_client import AzureDevOpsRestClient
from github_client import GitHubRestClient
from rocketchat_notifier import RocketChatNotifier, RocketChatNotifierError
from run_store import ClaimRequest, RunStore, TaskRun
from workflow_provider import NormalizedProviderEvent, WorkflowProviderClient

from .config import HarnessRuntimeConfig
from .image_analyzer import ImageAnalysisError, ImageAnalysisResult, ImageAnalyzer
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


@dataclass(frozen=True)
class ChatCommandResult:
    ok: bool
    command: str
    text: str
    run_id: str | None = None
    response_type: str = "ephemeral"
    attachments: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": self.text,
            "response_type": self.response_type,
        }
        if self.attachments:
            payload["attachments"] = self.attachments
        return payload


class HarnessBridge:
    _SUPPORTED_CHAT_COMMANDS = {"status", "detail", "pause", "resume", "add-context", "escalate"}
    _CHAT_COMMAND_ALIASES = {
        "add_context": "add-context",
        "context": "add-context",
        "details": "detail",
    }

    def __init__(
        self,
        *,
        config: HarnessRuntimeConfig,
        store: RunStore,
        ado_client: AzureDevOpsRestClient | None = None,
        github_client: GitHubRestClient | None = None,
        provider_clients: Mapping[str, WorkflowProviderClient] | None = None,
        openclaw_client: OpenClawWebhookClient | None = None,
        notifier: RocketChatNotifier | None = None,
        task_orchestrator: TaskRunOrchestrator | None = None,
        image_analyzer: ImageAnalyzer | None = None,
        run_id_factory: RunIdFactory | None = None,
    ):
        self.config = config
        self.store = store
        clients = dict(provider_clients or {})
        if ado_client is not None:
            clients.setdefault("azure-devops", ado_client)
        if github_client is not None:
            clients.setdefault("github", github_client)
        self.provider_clients = clients
        self.ado_client = ado_client or clients.get("azure-devops")
        self.github_client = github_client or clients.get("github")
        self.openclaw_client = openclaw_client
        self.notifier = notifier
        self.task_orchestrator = task_orchestrator
        self.image_analyzer = image_analyzer
        self.run_id_factory = run_id_factory or (lambda: str(uuid.uuid4()))

    def handle_ado_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> BridgeResult:
        return self.handle_provider_event(
            provider_type="azure-devops",
            event_type=event_type,
            payload=payload,
            source_id=source_id,
        )

    def handle_github_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> BridgeResult:
        return self.handle_provider_event(
            provider_type="github",
            event_type=event_type,
            payload=payload,
            source_id=source_id,
        )

    def handle_provider_event(
        self,
        *,
        provider_type: str,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> BridgeResult:
        provider = self._provider_client(provider_type)
        normalized = provider.normalize_event(event_type=event_type, payload=payload, source_id=source_id)

        if normalized.task_id and normalized.event_type.startswith("task."):
            return self._handle_task_event(normalized)
        if normalized.pr_id and normalized.event_type.startswith("pr."):
            return self._handle_pr_event(normalized)
        if normalized.ci_run_id and normalized.event_type.startswith("ci."):
            return self._handle_ci_event(normalized)
        return BridgeResult(accepted=False, action="ignored", reason="unsupported_event")

    def handle_chat_command(
        self,
        *,
        provider_type: str,
        payload: Mapping[str, Any],
    ) -> ChatCommandResult:
        command_payload = self._normalize_chat_command_payload(provider_type=provider_type, payload=payload)
        if command_payload is None:
            return ChatCommandResult(
                ok=False,
                command="unsupported",
                text="ClawHarness 未识别到有效命令。可用命令：status、detail、pause、resume、add-context、escalate。",
            )

        command = command_payload["command"]
        args_text = command_payload["args_text"]
        conversation_id = command_payload["conversation_id"]
        target, remainder = self._resolve_chat_command_target(
            args_text=args_text,
            conversation_id=conversation_id,
        )
        if target is None:
            return ChatCommandResult(
                ok=False,
                command=command,
                text="未找到目标 run。请使用 `status <run_id|task_key>` 或在已绑定的对话线程中执行命令。",
            )

        root_run = self._resolve_root_run(target)
        self._link_chat_context(root_run, provider_type=provider_type, conversation_id=conversation_id)
        self._record_chat_command(
            root_run=root_run,
            target_run=target,
            provider_type=provider_type,
            payload=command_payload,
            remainder=remainder,
        )

        if command == "status":
            return self._build_chat_status_response(root_run=root_run, target_run=target)
        if command == "detail":
            return self._build_chat_detail_response(root_run=root_run, target_run=target)
        if command == "pause":
            reason = remainder or "Paused by chat command"
            self._pause_run(
                root_run=root_run,
                target_run=target,
                provider_type=provider_type,
                reason=reason,
                user_label=command_payload["user_label"],
            )
            return self._build_chat_status_response(
                root_run=self.store.get_run(root_run.run_id) or root_run,
                target_run=self.store.get_run(target.run_id) or target,
                prefix="运行已暂停。",
            )
        if command == "resume":
            self._resume_run(
                root_run=root_run,
                target_run=target,
                provider_type=provider_type,
                user_label=command_payload["user_label"],
            )
            return self._build_chat_status_response(
                root_run=self.store.get_run(root_run.run_id) or root_run,
                target_run=self.store.get_run(target.run_id) or target,
                prefix="运行已恢复。",
            )
        if command == "add-context":
            if not remainder:
                return ChatCommandResult(
                    ok=False,
                    command=command,
                    run_id=root_run.run_id,
                    text="`add-context` 需要提供上下文文本，例如：`add-context run-1 这是新的限制条件`。",
                )
            analyses = self._add_chat_context(
                root_run=root_run,
                target_run=target,
                provider_type=provider_type,
                user_label=command_payload["user_label"],
                context_text=remainder,
                conversation_id=conversation_id,
                payload=payload,
            )
            prefix = "上下文已追加。"
            if analyses:
                prefix += "\n图片分析：" + "；".join(item.summary for item in analyses)
            return self._build_chat_detail_response(
                root_run=self.store.get_run(root_run.run_id) or root_run,
                target_run=self.store.get_run(target.run_id) or target,
                prefix=prefix,
            )
        if command == "escalate":
            reason = remainder or "Escalated by chat command"
            self._pause_run(
                root_run=root_run,
                target_run=target,
                provider_type=provider_type,
                reason=reason,
                user_label=command_payload["user_label"],
                command="escalate",
            )
            return self._build_chat_detail_response(
                root_run=self.store.get_run(root_run.run_id) or root_run,
                target_run=self.store.get_run(target.run_id) or target,
                prefix="运行已升级为人工介入。",
            )

        return ChatCommandResult(
            ok=False,
            command=command,
            text=f"暂不支持命令：{command}",
        )

    def _handle_task_event(self, normalized: NormalizedProviderEvent) -> BridgeResult:
        provider = self._provider_client(normalized.provider_type)
        task_key = normalized.task_key or normalized.task_id or "unknown-task"
        run_id = self.run_id_factory()
        session_key = self._session_key("task", task_key)
        run = TaskRun(
            run_id=run_id,
            provider_type=normalized.provider_type,
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

        task_context = self._load_task_context(
            normalized.provider_type,
            normalized.task_id,
            repo_id=normalized.repo_id,
        )
        prompt = self._build_task_prompt(normalized, claim.run.run_id, task_context)
        self.store.transition_status(
            claim.run.run_id,
            to_status="planning",
            expected_from="claimed",
        )
        notification_summary = f"Task {task_key} claimed and dispatched to OpenClaw"
        notification_details: dict[str, Any] = {
            "event_type": normalized.event_type,
            "dispatch_target": "openclaw-shell",
        }
        if self.task_orchestrator is None:
            if self.openclaw_client is None:
                self.store.append_audit(
                    claim.run.run_id,
                    "task_dispatch_rejected",
                    payload={"reason": "openclaw_shell_unavailable", "event_type": normalized.event_type},
                )
                return BridgeResult(
                    accepted=False,
                    action="task_dispatch_rejected",
                    run_id=claim.run.run_id,
                    reason="openclaw_shell_unavailable",
                    session_key=session_key,
                )
            self.openclaw_client.run_agent(
                message=prompt,
                name=f"{provider.display_name} Task",
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
            notification_summary = f"Task {task_key} claimed and queued for ClawHarness orchestration"
            notification_details["dispatch_target"] = "clawharness-orchestrator"
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
            summary=notification_summary,
            details=notification_details,
        )
        return BridgeResult(
            accepted=True,
            action="task_dispatched",
            run_id=claim.run.run_id,
            session_key=session_key,
        )

    def _handle_pr_event(self, normalized: NormalizedProviderEvent) -> BridgeResult:
        run = self.store.find_run_by_pr_id(normalized.pr_id or "")
        if run is None:
            return BridgeResult(accepted=False, action="pr_resume_skipped", reason="run_not_found")
        root_run = self._resolve_root_run(run)
        if self._is_pr_completion_event(normalized):
            return self._complete_pr_run(root_run, normalized)
        provider = self._provider_client(normalized.provider_type)
        if self.task_orchestrator is None:
            self.store.append_audit(
                root_run.run_id,
                "pr_feedback_rejected",
                payload={"reason": "task_orchestrator_required", "event_type": normalized.event_type},
            )
            return BridgeResult(
                accepted=False,
                action="pr_resume_skipped",
                run_id=root_run.run_id,
                reason="task_orchestrator_required",
                session_key=root_run.session_id,
            )
        if not self.store.record_event(
            self._fingerprint(normalized),
            source_type=normalized.event_type,
            source_id=normalized.source_id,
        ):
            return BridgeResult(
                accepted=False,
                action="pr_resume_skipped",
                run_id=root_run.run_id,
                reason="duplicate_event",
                session_key=root_run.session_id,
            )
        follow_up_lock = self.store.acquire_lock(
            self._follow_up_lock_key(root_run.run_id, "pr-feedback"),
            run_id=root_run.run_id,
            owner=self.config.owner,
            ttl_seconds=self._follow_up_lock_ttl_seconds(),
        )
        if not follow_up_lock.acquired:
            self.store.append_audit(
                root_run.run_id,
                "pr_feedback_skipped",
                payload={"reason": "follow_up_already_active", "event_type": normalized.event_type},
            )
            return BridgeResult(
                accepted=False,
                action="pr_resume_skipped",
                run_id=root_run.run_id,
                reason="follow_up_already_active",
                session_key=root_run.session_id,
            )

        comments = []
        if normalized.repo_id:
            comments = provider.list_pull_request_comments(normalized.repo_id, normalized.pr_id or "")
        self.store.append_audit(
            root_run.run_id,
            "pr_feedback_queued",
            payload={
                "pr_id": normalized.pr_id,
                "event_type": normalized.event_type,
                "comment_count": len(comments),
                "lock_key": self._follow_up_lock_key(root_run.run_id, "pr-feedback"),
                "lock_ttl_seconds": self._follow_up_lock_ttl_seconds(),
            },
        )
        threading.Thread(
            target=self._run_pr_feedback_resume,
            args=(root_run.run_id, comments, normalized.to_dict()),
            daemon=True,
        ).start()
        return BridgeResult(
            accepted=True,
            action="pr_feedback_queued",
            run_id=root_run.run_id,
            session_key=root_run.session_id,
        )

    def _is_pr_completion_event(self, normalized: NormalizedProviderEvent) -> bool:
        if normalized.event_type == "pr.merged":
            return True
        payload = normalized.payload
        if normalized.provider_type == "azure-devops":
            resource = payload.get("resource") if isinstance(payload.get("resource"), Mapping) else payload
            status = str(resource.get("status") or "").strip().lower()
            merge_status = str(resource.get("mergeStatus") or resource.get("merge_status") or "").strip().lower()
            return status == "completed" and merge_status == "succeeded"
        if normalized.provider_type == "github":
            pull_request = payload.get("pull_request") if isinstance(payload.get("pull_request"), Mapping) else {}
            action = str(payload.get("action") or "").strip().lower()
            return action == "closed" and bool(pull_request.get("merged"))
        return False

    def _complete_pr_run(self, root_run: TaskRun, normalized: NormalizedProviderEvent) -> BridgeResult:
        if not self.store.record_event(
            self._fingerprint(normalized),
            source_type=normalized.event_type,
            source_id=normalized.source_id,
        ):
            return BridgeResult(
                accepted=False,
                action="pr_completion_skipped",
                run_id=root_run.run_id,
                reason="duplicate_event",
                session_key=root_run.session_id,
            )

        completion_payload = self._pr_completion_payload(root_run, normalized)
        latest_root = self.store.get_run(root_run.run_id) or root_run
        if latest_root.status != "completed":
            self.store.transition_status(
                latest_root.run_id,
                to_status="completed",
                expected_from=(
                    "claimed",
                    "planning",
                    "coding",
                    "opening_pr",
                    "awaiting_ci",
                    "awaiting_review",
                    "awaiting_human",
                    "completed",
                ),
            )
        task_sync = self._sync_task_completion(latest_root, normalized)
        if task_sync is not None:
            completion_payload["task_sync"] = task_sync
        self.store.append_audit(
            latest_root.run_id,
            "pr_completed",
            payload=completion_payload,
        )
        refreshed_root = self.store.get_run(latest_root.run_id) or latest_root
        self._notify(
            event_type="pr_completed",
            task_key=refreshed_root.task_key,
            run_id=refreshed_root.run_id,
            summary=f"PR {normalized.pr_id} merged for {refreshed_root.task_key}; run marked completed",
            details=completion_payload,
        )
        return BridgeResult(
            accepted=True,
            action="pr_completed",
            run_id=refreshed_root.run_id,
            session_key=refreshed_root.session_id,
        )

    def _pr_completion_payload(self, root_run: TaskRun, normalized: NormalizedProviderEvent) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider_type": normalized.provider_type,
            "event_type": normalized.event_type,
            "pr_id": normalized.pr_id,
            "task_key": root_run.task_key,
            "actor": normalized.actor,
        }
        raw_payload = normalized.payload
        if normalized.provider_type == "azure-devops":
            resource = raw_payload.get("resource") if isinstance(raw_payload.get("resource"), Mapping) else raw_payload
            payload.update(
                {
                    "status": resource.get("status"),
                    "merge_status": resource.get("mergeStatus") or resource.get("merge_status"),
                    "source_branch": resource.get("sourceRefName"),
                    "target_branch": resource.get("targetRefName"),
                    "merge_commit": (
                        resource.get("lastMergeCommit", {}).get("commitId")
                        if isinstance(resource.get("lastMergeCommit"), Mapping)
                        else None
                    ),
                    "closed_date": resource.get("closedDate"),
                }
            )
        elif normalized.provider_type == "github":
            pull_request = raw_payload.get("pull_request") if isinstance(raw_payload.get("pull_request"), Mapping) else {}
            payload.update(
                {
                    "status": pull_request.get("state"),
                    "merge_status": "succeeded" if pull_request.get("merged") else "not_merged",
                    "source_branch": (
                        pull_request.get("head", {}).get("ref")
                        if isinstance(pull_request.get("head"), Mapping)
                        else None
                    ),
                    "target_branch": (
                        pull_request.get("base", {}).get("ref")
                        if isinstance(pull_request.get("base"), Mapping)
                        else None
                    ),
                    "merge_commit": pull_request.get("merge_commit_sha"),
                    "closed_date": pull_request.get("closed_at"),
                }
            )
        return payload

    def _sync_task_completion(
        self,
        root_run: TaskRun,
        normalized: NormalizedProviderEvent,
    ) -> dict[str, Any] | None:
        provider = self.provider_clients.get(normalized.provider_type)
        complete_task = getattr(provider, "complete_task", None)
        if complete_task is None:
            return None

        comment = (
            f"ClawHarness automatically marked `{root_run.task_key}` complete after PR {normalized.pr_id} merged."
        )
        payload = {
            "provider_type": normalized.provider_type,
            "task_id": root_run.task_id,
            "task_key": root_run.task_key,
            "pr_id": normalized.pr_id,
        }
        try:
            response = complete_task(root_run.task_id, repo_id=root_run.repo_id, comment=comment)
            payload["result"] = "completed"
            if isinstance(response, Mapping):
                fields = response.get("fields")
                payload["task_state"] = (
                    fields.get("System.State")
                    if isinstance(fields, Mapping)
                    else response.get("state")
                )
            self.store.append_audit(root_run.run_id, "task_completion_synced", payload=payload)
            return payload
        except Exception as exc:
            payload.update(
                {
                    "result": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            self.store.append_audit(root_run.run_id, "task_completion_sync_failed", payload=payload)
            return payload

    def _handle_ci_event(self, normalized: NormalizedProviderEvent) -> BridgeResult:
        provider = self._provider_client(normalized.provider_type)
        run = self.store.find_run_by_ci_run_id(normalized.ci_run_id or "")
        if run is None and normalized.pr_id:
            candidate = self.store.find_run_by_pr_id(normalized.pr_id)
            if candidate is not None and normalized.ci_run_id:
                root_candidate = self._resolve_root_run(candidate)
                self.store.update_run_fields(root_candidate.run_id, ci_run_id=normalized.ci_run_id)
                run = self.store.get_run(root_candidate.run_id) or root_candidate
        if run is None:
            return BridgeResult(accepted=False, action="ci_resume_skipped", reason="run_not_found")
        root_run = self._resolve_root_run(run)
        if self.task_orchestrator is None:
            self.store.append_audit(
                root_run.run_id,
                "ci_recovery_rejected",
                payload={"reason": "task_orchestrator_required", "event_type": normalized.event_type},
            )
            return BridgeResult(
                accepted=False,
                action="ci_resume_skipped",
                run_id=root_run.run_id,
                reason="task_orchestrator_required",
                session_key=root_run.session_id,
            )
        if not self.store.record_event(
            self._fingerprint(normalized),
            source_type=normalized.event_type,
            source_id=normalized.source_id,
        ):
            return BridgeResult(
                accepted=False,
                action="ci_resume_skipped",
                run_id=root_run.run_id,
                reason="duplicate_event",
                session_key=root_run.session_id,
            )
        follow_up_lock = self.store.acquire_lock(
            self._follow_up_lock_key(root_run.run_id, "ci-recovery"),
            run_id=root_run.run_id,
            owner=self.config.owner,
            ttl_seconds=self._follow_up_lock_ttl_seconds(),
        )
        if not follow_up_lock.acquired:
            self.store.append_audit(
                root_run.run_id,
                "ci_recovery_skipped",
                payload={"reason": "follow_up_already_active", "event_type": normalized.event_type},
            )
            return BridgeResult(
                accepted=False,
                action="ci_resume_skipped",
                run_id=root_run.run_id,
                reason="follow_up_already_active",
                session_key=root_run.session_id,
            )

        build_summary = provider.get_ci_run(normalized.ci_run_id or "", repo_id=normalized.repo_id or root_run.repo_id)
        self.store.append_audit(
            root_run.run_id,
            "ci_recovery_queued",
            payload={
                "ci_run_id": normalized.ci_run_id,
                "event_type": normalized.event_type,
                "lock_key": self._follow_up_lock_key(root_run.run_id, "ci-recovery"),
                "lock_ttl_seconds": self._follow_up_lock_ttl_seconds(),
            },
        )
        threading.Thread(
            target=self._run_ci_recovery,
            args=(root_run.run_id, build_summary, normalized.to_dict()),
            daemon=True,
        ).start()
        self._notify(
            event_type="ci_failed",
            task_key=root_run.task_key,
            run_id=root_run.run_id,
            summary=f"CI failure for {root_run.task_key} queued for recovery",
            details={"ci_run_id": normalized.ci_run_id},
        )
        return BridgeResult(
            accepted=True,
            action="ci_recovery_queued",
            run_id=root_run.run_id,
            session_key=root_run.session_id,
        )

    def _load_task_context(
        self,
        provider_type: str,
        task_id: str | None,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        if not task_id:
            return {}
        provider = self._provider_client(provider_type)
        try:
            return provider.get_task(
                task_id,
                repo_id=repo_id,
                fields=[
                    "System.Title",
                    "System.Description",
                    "System.State",
                    "System.TeamProject",
                    "System.AssignedTo",
                ],
            )
        except Exception as exc:
            return {"task_fetch_error": str(exc), "task_id": task_id}

    def _build_task_prompt(self, normalized: NormalizedProviderEvent, run_id: str, task_context: dict[str, Any]) -> str:
        provider = self._provider_client(normalized.provider_type)
        return "\n".join(
            [
                f"Handle {provider.display_name} task event `{normalized.event_type}`.",
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

    def _fingerprint(self, normalized: NormalizedProviderEvent) -> str:
        if normalized.source_id:
            return f"{normalized.provider_type}:{normalized.event_type}:{normalized.source_id}"
        stable = json.dumps(normalized.to_dict(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        return f"{normalized.provider_type}:{normalized.event_type}:{digest}"

    def _provider_client(self, provider_type: str) -> WorkflowProviderClient:
        client = self.provider_clients.get(provider_type)
        if client is None:
            raise KeyError(f"Provider client is not configured: {provider_type}")
        return client

    def _session_key(self, prefix: str, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._:-]+", "-", value).strip("-") or "unknown"
        base_session_key = (
            self.config.openclaw_hooks.default_session_key
            if self.config.openclaw_hooks is not None
            else f"core:{self.config.owner}"
        )
        return f"{base_session_key}:{prefix}:{slug}"

    def _resolve_root_run(self, run: TaskRun) -> TaskRun:
        current = run
        visited = {run.run_id}
        while True:
            parent = self.store.get_parent_run(current.run_id)
            if parent is None or parent.run_id in visited:
                return current
            visited.add(parent.run_id)
            current = parent

    def _normalize_chat_command_payload(
        self,
        *,
        provider_type: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        raw_text = str(
            payload.get("text")
            or payload.get("message")
            or payload.get("msg")
            or ""
        ).strip()
        direct_command = str(payload.get("command") or "").strip()
        if provider_type in {"bot-view", "weixin"} and direct_command:
            normalized_command = self._normalize_chat_command_name(direct_command)
            if normalized_command in self._SUPPORTED_CHAT_COMMANDS:
                selector = str(payload.get("run_id") or payload.get("task_key") or payload.get("selector") or "").strip()
                detail = str(
                    payload.get("context_text")
                    or payload.get("reason")
                    or payload.get("detail")
                    or payload.get("args_text")
                    or payload.get("argument")
                    or payload.get("note")
                    or ""
                ).strip()
                args_text = " ".join(part for part in (selector, detail) if part).strip()
                user_label = str(
                    payload.get("user_label")
                    or payload.get("user_name")
                    or payload.get("username")
                    or payload.get("userName")
                    or payload.get("user_id")
                    or payload.get("userId")
                    or "unknown-user"
                )
                return {
                    "command": normalized_command,
                    "args_text": args_text,
                    "raw_text": raw_text or " ".join(part for part in (normalized_command, args_text) if part).strip(),
                    "conversation_id": self._conversation_id(payload),
                    "user_label": user_label,
                }
        trigger_word = str(payload.get("trigger_word") or payload.get("triggerWord") or "").strip().lstrip("/")
        command_name = str(payload.get("command") or "").strip().lstrip("/")
        conversation_id = self._conversation_id(payload)
        user_label = str(
            payload.get("user_name")
            or payload.get("username")
            or payload.get("userName")
            or payload.get("user_id")
            or payload.get("userId")
            or "unknown-user"
        )

        command_text = raw_text
        if command_text.startswith("/"):
            slash, _, remainder = command_text.partition(" ")
            if slash.lstrip("/").lower() in {"clawharness", "harness", "claw"}:
                command_text = remainder.strip()
        elif command_name.lower() in {"clawharness", "harness", "claw"}:
            command_text = raw_text
        elif trigger_word:
            normalized_trigger = self._normalize_chat_command_name(trigger_word)
            if normalized_trigger in self._SUPPORTED_CHAT_COMMANDS and (
                not command_text or self._normalize_chat_command_name(command_text.split(" ", 1)[0]) != normalized_trigger
            ):
                command_text = f"{normalized_trigger} {command_text}".strip()

        if not command_text:
            return None

        command, _, remainder = command_text.partition(" ")
        normalized_command = self._normalize_chat_command_name(command)
        if normalized_command not in self._SUPPORTED_CHAT_COMMANDS:
            return None

        return {
            "command": normalized_command,
            "args_text": remainder.strip(),
            "raw_text": raw_text,
            "conversation_id": conversation_id,
            "user_label": user_label,
        }

    def _normalize_chat_command_name(self, value: str) -> str:
        normalized = value.strip().lower().lstrip("/")
        return self._CHAT_COMMAND_ALIASES.get(normalized, normalized)

    def _conversation_id(self, payload: Mapping[str, Any]) -> str | None:
        for key in (
            "conversation_id",
            "conversationId",
            "thread_id",
            "threadId",
            "tmid",
            "channel_id",
            "channelId",
            "room_id",
            "roomId",
            "channel_name",
            "session_key",
            "sessionKey",
            "open_id",
            "openId",
        ):
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _resolve_chat_command_target(
        self,
        *,
        args_text: str,
        conversation_id: str | None,
    ) -> tuple[TaskRun | None, str]:
        linked_target = self._find_chat_target(conversation_id=conversation_id)
        if not args_text:
            return linked_target, ""

        selector, has_separator, remainder = args_text.partition(" ")
        explicit_target = self._find_chat_target(selector=selector)
        if explicit_target is not None:
            return explicit_target, remainder.strip() if has_separator else ""
        return linked_target, args_text

    def _find_chat_target(
        self,
        *,
        selector: str | None = None,
        conversation_id: str | None = None,
    ) -> TaskRun | None:
        if selector:
            run = self.store.get_run(selector)
            if run is not None:
                return run
            active = self.store.find_active_run_by_task_key(selector)
            if active is not None:
                return active
            latest = self.store.list_runs(task_key=selector, limit=1)
            if latest:
                return latest[0]
        if conversation_id:
            link = self.store.get_thread_link(conversation_id)
            if link is not None:
                return self.store.get_run(link["run_id"])
        return None

    def _link_chat_context(
        self,
        root_run: TaskRun,
        *,
        provider_type: str,
        conversation_id: str | None,
    ) -> None:
        if not conversation_id:
            return
        self.store.link_thread(
            conversation_id,
            run_id=root_run.run_id,
            session_id=root_run.session_id,
            provider_type=provider_type,
        )
        if root_run.chat_thread_id != conversation_id:
            self.store.update_run_fields(root_run.run_id, chat_thread_id=conversation_id)
            self.store.append_audit(
                root_run.run_id,
                "chat_thread_linked",
                payload={"chat_thread_id": conversation_id, "provider_type": provider_type},
            )

    def _record_chat_command(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        provider_type: str,
        payload: Mapping[str, Any],
        remainder: str,
    ) -> None:
        audit_payload = {
            "provider_type": provider_type,
            "command": payload["command"],
            "raw_text": payload["raw_text"],
            "args_text": payload["args_text"],
            "remainder": remainder,
            "conversation_id": payload["conversation_id"],
            "user_label": payload["user_label"],
            "target_run_id": target_run.run_id,
            "root_run_id": root_run.run_id,
        }
        self.store.append_audit(root_run.run_id, "chat_command_received", payload=audit_payload)
        if target_run.run_id != root_run.run_id:
            self.store.append_audit(target_run.run_id, "chat_command_received", payload=audit_payload)

    def _pause_run(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        provider_type: str,
        reason: str,
        user_label: str,
        command: str = "pause",
    ) -> None:
        self.store.record_checkpoint(
            target_run.run_id,
            "chat_pause",
            payload={
                "previous_status": target_run.status,
                "command": command,
                "reason": reason,
                "provider_type": provider_type,
                "user_label": user_label,
            },
        )
        if root_run.run_id != target_run.run_id:
            self.store.record_checkpoint(
                root_run.run_id,
                "chat_pause",
                payload={
                    "previous_status": root_run.status,
                    "command": command,
                    "reason": reason,
                    "provider_type": provider_type,
                    "user_label": user_label,
                    "target_run_id": target_run.run_id,
                },
            )
        if self.task_orchestrator is not None:
            self.task_orchestrator._block_run(
                target_run.run_id,
                reason=reason,
                details={
                    "source": "chat",
                    "command": command,
                    "provider_type": provider_type,
                    "user_label": user_label,
                },
                parent_run_id=root_run.run_id if root_run.run_id != target_run.run_id else None,
            )
        else:
            self.store.transition_status(
                target_run.run_id,
                to_status="awaiting_human",
                expected_from=(target_run.status, "claimed", "planning", "coding", "opening_pr", "awaiting_ci", "awaiting_review"),
                last_error=reason,
                released_lock=True,
            )

    def _resume_run(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        provider_type: str,
        user_label: str,
    ) -> None:
        refreshed_root = self.store.get_run(root_run.run_id) or root_run
        refreshed_target = self.store.get_run(target_run.run_id) or target_run
        self._restore_run_from_pause(refreshed_target, provider_type=provider_type, user_label=user_label)
        if refreshed_root.run_id != refreshed_target.run_id and refreshed_root.status == "awaiting_human":
            self._restore_run_from_pause(refreshed_root, provider_type=provider_type, user_label=user_label)

    def _restore_run_from_pause(
        self,
        run: TaskRun,
        *,
        provider_type: str,
        user_label: str,
    ) -> None:
        if run.status != "awaiting_human":
            return
        resume_status = self._latest_pause_status(run.run_id) or "planning"
        self.store.transition_status(
            run.run_id,
            to_status=resume_status,
            expected_from="awaiting_human",
            last_error=None,
        )
        self.store.append_audit(
            run.run_id,
            "chat_command_applied",
            payload={
                "command": "resume",
                "provider_type": provider_type,
                "user_label": user_label,
                "restored_status": resume_status,
            },
        )
        self.store.record_checkpoint(
            run.run_id,
            "chat_resume",
            payload={
                "provider_type": provider_type,
                "user_label": user_label,
                "restored_status": resume_status,
            },
        )

    def _latest_pause_status(self, run_id: str) -> str | None:
        for checkpoint in reversed(self.store.list_checkpoints(run_id)):
            if checkpoint.get("stage") != "chat_pause":
                continue
            payload = self._parse_payload_json(checkpoint.get("payload_json"))
            if isinstance(payload, Mapping):
                previous_status = payload.get("previous_status")
                if isinstance(previous_status, str) and previous_status:
                    return previous_status
        return None

    def _add_chat_context(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        provider_type: str,
        user_label: str,
        context_text: str,
        conversation_id: str | None,
        payload: Mapping[str, Any],
    ) -> list[ImageAnalysisResult]:
        artifact_payload = {
            "provider_type": provider_type,
            "user_label": user_label,
            "conversation_id": conversation_id,
            "text": context_text,
        }
        self.store.record_artifact(
            target_run.run_id,
            "chat-context",
            f"chat-context-{uuid.uuid4().hex[:8]}",
            payload=artifact_payload,
        )
        self.store.append_audit(
            target_run.run_id,
            "chat_context_added",
            payload=artifact_payload,
        )
        self.store.record_checkpoint(
            target_run.run_id,
            "chat_context_added",
            payload=artifact_payload,
        )
        if target_run.run_id != root_run.run_id:
            self.store.record_artifact(
                root_run.run_id,
                "chat-context",
                f"chat-context-{uuid.uuid4().hex[:8]}",
                payload={**artifact_payload, "target_run_id": target_run.run_id},
            )
            self.store.append_audit(
                root_run.run_id,
                "chat_context_added",
                payload={**artifact_payload, "target_run_id": target_run.run_id},
            )
        self._record_chat_attachments(root_run=root_run, target_run=target_run, provider_type=provider_type, payload=payload)
        return self._analyze_chat_images(
            root_run=root_run,
            target_run=target_run,
            provider_type=provider_type,
            context_text=context_text,
            payload=payload,
        )

    def _chat_attachments(self, payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        attachments: list[Mapping[str, Any]] = []
        raw_attachments = payload.get("attachments")
        if isinstance(raw_attachments, list):
            attachments.extend(item for item in raw_attachments if isinstance(item, Mapping))
        raw_files = payload.get("files")
        if isinstance(raw_files, list):
            attachments.extend(item for item in raw_files if isinstance(item, Mapping))
        return attachments

    def _is_image_attachment(self, attachment: Mapping[str, Any]) -> bool:
        mime = str(attachment.get("contentType") or attachment.get("mime") or "").lower()
        return mime.startswith("image/") or bool(attachment.get("image_url") or attachment.get("imageUrl"))

    def _record_chat_attachments(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        provider_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        for attachment in self._chat_attachments(payload):
            artifact_type = "chat-attachment"
            if self._is_image_attachment(attachment):
                artifact_type = "chat-image"
            attachment_payload = {
                "provider_type": provider_type,
                "attachment": dict(attachment),
            }
            self.store.record_artifact(
                target_run.run_id,
                artifact_type,
                f"{artifact_type}-{uuid.uuid4().hex[:8]}",
                payload=attachment_payload,
            )
            if target_run.run_id != root_run.run_id:
                self.store.record_artifact(
                    root_run.run_id,
                    artifact_type,
                    f"{artifact_type}-{uuid.uuid4().hex[:8]}",
                    payload={**attachment_payload, "target_run_id": target_run.run_id},
                )

    def _analyze_chat_images(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        provider_type: str,
        context_text: str,
        payload: Mapping[str, Any],
    ) -> list[ImageAnalysisResult]:
        if self.image_analyzer is None:
            return []

        results: list[ImageAnalysisResult] = []
        for attachment in self._chat_attachments(payload):
            if not self._is_image_attachment(attachment):
                continue
            try:
                analysis = self.image_analyzer.analyze(
                    context_text=context_text,
                    attachment=attachment,
                    task_key=root_run.task_key,
                )
            except ImageAnalysisError as exc:
                failure_payload = {
                    "provider_type": provider_type,
                    "error": str(exc),
                    "attachment": dict(attachment),
                }
                self.store.append_audit(target_run.run_id, "image_analysis_failed", payload=failure_payload)
                if target_run.run_id != root_run.run_id:
                    self.store.append_audit(
                        root_run.run_id,
                        "image_analysis_failed",
                        payload={**failure_payload, "target_run_id": target_run.run_id},
                    )
                continue

            analysis_payload = {
                "provider_type": provider_type,
                "model": analysis.model,
                "summary": analysis.summary,
                "response_id": analysis.response_id,
                "attachment": dict(attachment),
            }
            self.store.record_artifact(
                target_run.run_id,
                "image-analysis",
                f"image-analysis-{uuid.uuid4().hex[:8]}",
                payload=analysis_payload,
            )
            self.store.append_audit(
                target_run.run_id,
                "image_analysis_completed",
                payload=analysis_payload,
            )
            self.store.record_checkpoint(
                target_run.run_id,
                "image_analysis",
                payload={
                    "model": analysis.model,
                    "summary": analysis.summary,
                    "response_id": analysis.response_id,
                },
            )
            if target_run.run_id != root_run.run_id:
                self.store.record_artifact(
                    root_run.run_id,
                    "image-analysis",
                    f"image-analysis-{uuid.uuid4().hex[:8]}",
                    payload={**analysis_payload, "target_run_id": target_run.run_id},
                )
                self.store.append_audit(
                    root_run.run_id,
                    "image_analysis_completed",
                    payload={**analysis_payload, "target_run_id": target_run.run_id},
                )
            results.append(analysis)
        return results

    def _build_chat_status_response(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        prefix: str | None = None,
    ) -> ChatCommandResult:
        latest_target = self.store.get_run(target_run.run_id) or target_run
        latest_root = self.store.get_run(root_run.run_id) or root_run
        child_links = self.store.list_child_relationships(latest_root.run_id)
        lines = []
        if prefix:
            lines.append(prefix)
        lines.append(f"{latest_root.task_key} 当前状态：{latest_root.status}")
        if latest_target.run_id != latest_root.run_id:
            lines.append(f"目标子 run：{latest_target.run_id} / {latest_target.status}")
        if latest_root.last_error:
            lines.append(f"阻塞原因：{latest_root.last_error}")
        attachment = {
            "color": "#1d74f5",
            "title": "ClawHarness Status",
            "fields": [
                {"title": "Task", "value": latest_root.task_key, "short": True},
                {"title": "Run", "value": latest_root.run_id, "short": True},
                {"title": "Status", "value": latest_root.status, "short": True},
                {"title": "Branch", "value": latest_root.branch_name or "-", "short": False},
                {"title": "PR / CI", "value": f"PR: {latest_root.pr_id or '-'} / CI: {latest_root.ci_run_id or '-'}", "short": False},
                {"title": "Child Runs", "value": str(len(child_links)), "short": True},
            ],
        }
        return ChatCommandResult(
            ok=True,
            command="status",
            run_id=latest_root.run_id,
            text="\n".join(lines),
            attachments=[attachment],
        )

    def _build_chat_detail_response(
        self,
        *,
        root_run: TaskRun,
        target_run: TaskRun,
        prefix: str | None = None,
    ) -> ChatCommandResult:
        latest_target = self.store.get_run(target_run.run_id) or target_run
        latest_root = self.store.get_run(root_run.run_id) or root_run
        audit = self.store.list_audit(latest_target.run_id)[-3:]
        checkpoints = self.store.list_checkpoints(latest_target.run_id)[-3:]
        child_links = self.store.list_child_relationships(latest_root.run_id)
        recent_events = ", ".join(entry["event_type"] for entry in audit) or "-"
        recent_checkpoints = ", ".join(entry["stage"] for entry in checkpoints) or "-"
        lines = []
        if prefix:
            lines.append(prefix)
        lines.append(f"{latest_root.task_key} / root {latest_root.run_id} / {latest_root.status}")
        if latest_target.run_id != latest_root.run_id:
            lines.append(f"target {latest_target.run_id} / {latest_target.status}")
        lines.append(f"最近事件：{recent_events}")
        lines.append(f"最近检查点：{recent_checkpoints}")
        child_summary = ", ".join(
            f"{link['relation_type']}:{link['run'].status}"
            for link in child_links[:4]
        ) or "-"
        attachment = {
            "color": "#2eb67d",
            "title": "ClawHarness Detail",
            "fields": [
                {"title": "Workspace", "value": latest_root.workspace_path or "-", "short": False},
                {"title": "Session", "value": latest_root.session_id, "short": False},
                {"title": "Recent Events", "value": recent_events, "short": False},
                {"title": "Recent Checkpoints", "value": recent_checkpoints, "short": False},
                {"title": "Child Summary", "value": child_summary, "short": False},
            ],
        }
        return ChatCommandResult(
            ok=True,
            command="detail",
            run_id=latest_root.run_id,
            text="\n".join(lines),
            attachments=[attachment],
        )

    def _parse_payload_json(self, payload: Any) -> Any:
        if not isinstance(payload, str) or not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

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

    def _run_pr_feedback_resume(
        self,
        run_id: str,
        comments: list[dict[str, Any]],
        event_payload: Mapping[str, Any],
    ) -> None:
        if self.task_orchestrator is None:
            return
        try:
            self.task_orchestrator.resume_from_pr_feedback(
                run_id,
                comments=list(comments),
                event_payload=dict(event_payload),
            )
        except Exception as exc:
            self.store.append_audit(
                run_id,
                "pr_feedback_resume_failed",
                payload={"error": str(exc), "error_type": type(exc).__name__},
            )
        finally:
            self.store.release_lock(self._follow_up_lock_key(run_id, "pr-feedback"), owner=self.config.owner)

    def _run_ci_recovery(
        self,
        run_id: str,
        build_summary: Mapping[str, Any],
        event_payload: Mapping[str, Any],
    ) -> None:
        if self.task_orchestrator is None:
            return
        try:
            self.task_orchestrator.resume_from_ci_failure(
                run_id,
                build_summary=dict(build_summary),
                event_payload=dict(event_payload),
            )
        except Exception as exc:
            self.store.append_audit(
                run_id,
                "ci_recovery_failed",
                payload={"error": str(exc), "error_type": type(exc).__name__},
            )
        finally:
            self.store.release_lock(self._follow_up_lock_key(run_id, "ci-recovery"), owner=self.config.owner)

    def _follow_up_lock_key(self, run_id: str, relation_type: str) -> str:
        return f"followup:{run_id}:{relation_type}"

    def _follow_up_lock_ttl_seconds(self) -> int:
        return max(self.config.runtime.lock_ttl_seconds, self.config.executor.timeout_seconds + 300)
