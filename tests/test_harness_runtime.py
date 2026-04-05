from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from ado_client import AzureDevOpsRestClient
from harness_runtime import HarnessBridge, OpenClawWebhookClient, load_harness_runtime_config
from rocketchat_notifier import RocketChatNotifier
from run_store import RunStore, TaskRun


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses: list[tuple[int, dict[str, str], bytes]] = []

    def queue_json(self, payload: dict) -> None:
        self.responses.append((200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")))

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
            }
        )
        if not self.responses:
            return 200, {"Content-Type": "application/json"}, b"{}"
        return self.responses.pop(0)


class RecordingTaskOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.event = threading.Event()

    def run_claimed_task(self, run_id: str, *, task_context: dict[str, object]) -> None:
        self.calls.append({"method": "run_claimed_task", "run_id": run_id, "task_context": task_context})
        self.event.set()

    def resume_from_pr_feedback(
        self,
        run_id: str,
        *,
        comments: list[dict[str, object]],
        event_payload: dict[str, object],
    ) -> None:
        self.calls.append(
            {
                "method": "resume_from_pr_feedback",
                "run_id": run_id,
                "comments": comments,
                "event_payload": event_payload,
            }
        )
        self.event.set()

    def resume_from_ci_failure(
        self,
        run_id: str,
        *,
        build_summary: dict[str, object],
        event_payload: dict[str, object],
    ) -> None:
        self.calls.append(
            {
                "method": "resume_from_ci_failure",
                "run_id": run_id,
                "build_summary": build_summary,
                "event_payload": event_payload,
            }
        )
        self.event.set()


class HarnessRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

        providers_path = self.base / "providers.yaml"
        policy_path = self.base / "harness-policy.yaml"
        openclaw_path = self.base / "openclaw.json"

        providers_path.write_text(
            """
providers:
  task_pr_ci:
    family: azure-devops
    mode: ado-rest
    fallback_mode: ado-rest
    base_url: https://dev.azure.com/example-org
    project: ExampleProject
    auth:
      type: pat
      secret_env: ADO_PAT
    events:
      mode: webhook
      webhook_secret_env: ADO_WEBHOOK_SECRET
  chat:
    family: rocketchat
    mode: rocketchat-webhook
    room: "#ai-dev"
    webhook_url_env: RC_WEBHOOK_URL
  executor:
    family: acp
    mode: codex-acp
    harness: codex
    backend: acpx
    runtime:
      mode: persistent
      timeout_seconds: 3600
runtime:
  storage:
    kind: sqlite
    path: DB_PATH
  workspace_root: D:/Repos/workspaces
  branch_prefix: ai
  lock_ttl_seconds: 1800
  dedupe_ttl_seconds: 86400
  audit_retention_days: 30
""".replace("DB_PATH", str(self.base / "harness.db").replace("\\", "/")),
            encoding="utf-8",
        )
        policy_path.write_text(
            """
policy:
  vcs:
    allow_protected_branch_push: false
""",
            encoding="utf-8",
        )
        openclaw_path.write_text(
            json.dumps(
                {
                    "gatewayBaseUrl": "http://127.0.0.1:18789",
                    "gatewayToken": "${OPENCLAW_GATEWAY_TOKEN}",
                    "hooks": {
                        "enabled": True,
                        "token": "${OPENCLAW_HOOKS_TOKEN}",
                        "path": "/hooks",
                        "defaultAgentId": "hooks",
                        "defaultSessionKey": "hook:harness",
                        "wakeMode": "now",
                        "owner": "harness-bridge",
                        "ingressToken": "${HARNESS_INGRESS_TOKEN}",
                    },
                }
            ),
            encoding="utf-8",
        )
        self.config = load_harness_runtime_config(
            providers_path=providers_path,
            policy_path=policy_path,
            openclaw_path=openclaw_path,
            env={
                "ADO_PAT": "ado-secret",
                "ADO_WEBHOOK_SECRET": "ado-webhook",
                "RC_WEBHOOK_URL": "https://chat.example/hooks/1/abc",
                "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "HARNESS_INGRESS_TOKEN": "ingress-secret",
            },
        )
        self.store = RunStore(self.config.runtime.sqlite_path)
        self.store.initialize()

        self.ado_transport = RecordingTransport()
        self.openclaw_transport = RecordingTransport()
        self.chat_transport = RecordingTransport()

        self.ado_transport.queue_json({"id": 123, "fields": {"System.Title": "Fix bug"}})
        self.ado_client = AzureDevOpsRestClient(
            base_url=self.config.azure_devops.base_url,
            project=self.config.azure_devops.project,
            pat=self.config.azure_devops.pat,
            transport=self.ado_transport,
        )
        self.openclaw_client = OpenClawWebhookClient(
            base_url=self.config.openclaw_hooks.base_url,
            token=self.config.openclaw_hooks.token,
            path=self.config.openclaw_hooks.path,
            transport=self.openclaw_transport,
        )
        self.notifier = RocketChatNotifier(
            webhook_url=self.config.rocketchat.webhook_url or "https://chat.example/hooks/1/abc",
            default_channel=self.config.rocketchat.channel,
            transport=self.chat_transport,
        )
        self.bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            run_id_factory=lambda: "run-1",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_load_harness_runtime_config_resolves_secrets(self) -> None:
        self.assertEqual("ado-secret", self.config.azure_devops.pat)
        self.assertEqual("https://chat.example/hooks/1/abc", self.config.rocketchat.webhook_url)
        self.assertEqual("gateway-secret", self.config.openclaw_gateway_token)
        self.assertEqual("hook-secret", self.config.openclaw_hooks.token)
        self.assertEqual("ingress-secret", self.config.ingress_token)

    def test_load_harness_runtime_config_expands_user_paths(self) -> None:
        providers_path = self.base / "providers-home.yaml"
        policy_path = self.base / "policy-home.yaml"
        openclaw_path = self.base / "openclaw-home.json"
        providers_path.write_text(
            """
providers:
  task_pr_ci:
    family: azure-devops
    mode: ado-rest
    fallback_mode: ado-rest
    base_url: https://dev.azure.com/example-org
    project: ExampleProject
    auth:
      type: pat
      secret_env: ADO_PAT
  chat:
    family: rocketchat
    mode: rocketchat-webhook
    webhook_url_env: RC_WEBHOOK_URL
  executor:
    family: acp
    mode: codex-acp
    harness: codex
    backend: acpx
    runtime:
      timeout_seconds: 3600
runtime:
  storage:
    kind: sqlite
    path: ~/.openclaw/harness/harness.db
  workspace_root: ~/.openclaw/workspace/harness
  branch_prefix: ai
""",
            encoding="utf-8",
        )
        policy_path.write_text("policy: {}\n", encoding="utf-8")
        openclaw_path.write_text(
            json.dumps(
                {
                    "gatewayBaseUrl": "http://127.0.0.1:18789",
                    "hooks": {
                        "token": "${OPENCLAW_HOOKS_TOKEN}",
                        "path": "/hooks",
                        "defaultAgentId": "hooks",
                        "defaultSessionKey": "hook:harness",
                        "wakeMode": "now",
                        "owner": "harness-bridge",
                    },
                }
            ),
            encoding="utf-8",
        )

        config = load_harness_runtime_config(
            providers_path=providers_path,
            policy_path=policy_path,
            openclaw_path=openclaw_path,
            env={
                "ADO_PAT": "ado-secret",
                "RC_WEBHOOK_URL": "https://chat.example/hooks/1/abc",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "USERPROFILE": str(self.base),
            },
        )

        self.assertEqual(self.base / ".openclaw" / "harness" / "harness.db", Path(config.runtime.sqlite_path))
        self.assertEqual(self.base / ".openclaw" / "workspace" / "harness", Path(config.runtime.workspace_root))

    def test_load_harness_runtime_config_resolves_general_placeholders(self) -> None:
        providers_path = self.base / "providers-env.yaml"
        policy_path = self.base / "policy-env.yaml"
        openclaw_path = self.base / "openclaw-env.json"
        providers_path.write_text(
            """
providers:
  task_pr_ci:
    family: azure-devops
    mode: ${ADO_MODE}
    fallback_mode: ado-rest
    base_url: ${ADO_BASE_URL}
    project: ${ADO_PROJECT}
    auth:
      type: pat
      secret_env: ADO_PAT
  chat:
    family: rocketchat
    mode: ${CHAT_MODE}
    webhook_url_env: RC_WEBHOOK_URL
  executor:
    family: acp
    mode: ${EXECUTOR_MODE}
    harness: ${EXECUTOR_HARNESS}
    backend: ${EXECUTOR_BACKEND}
    runtime:
      timeout_seconds: 3600
runtime:
  storage:
    kind: sqlite
    path: ~/.openclaw/harness/harness.db
  workspace_root: ~/.openclaw/workspace/harness
  branch_prefix: ${BRANCH_PREFIX}
""",
            encoding="utf-8",
        )
        policy_path.write_text("policy: {}\n", encoding="utf-8")
        openclaw_path.write_text(
            json.dumps(
                {
                    "gatewayBaseUrl": "${OPENCLAW_BASE_URL}",
                    "gatewayToken": "${OPENCLAW_GATEWAY_TOKEN}",
                    "hooks": {
                        "token": "${OPENCLAW_HOOKS_TOKEN}",
                        "path": "${OPENCLAW_HOOKS_PATH}",
                        "defaultAgentId": "${OPENCLAW_AGENT_ID}",
                        "defaultSessionKey": "${OPENCLAW_SESSION_KEY}",
                        "wakeMode": "${OPENCLAW_WAKE_MODE}",
                        "owner": "${OPENCLAW_OWNER}",
                    },
                }
            ),
            encoding="utf-8",
        )

        config = load_harness_runtime_config(
            providers_path=providers_path,
            policy_path=policy_path,
            openclaw_path=openclaw_path,
            env={
                "ADO_MODE": "ado-rest",
                "ADO_BASE_URL": "https://dev.azure.com/example-org",
                "ADO_PROJECT": "ExampleProject",
                "ADO_PAT": "ado-secret",
                "CHAT_MODE": "rocketchat-webhook",
                "RC_WEBHOOK_URL": "https://chat.example/hooks/1/abc",
                "EXECUTOR_MODE": "codex-acp",
                "EXECUTOR_HARNESS": "codex",
                "EXECUTOR_BACKEND": "acpx",
                "BRANCH_PREFIX": "ai",
                "OPENCLAW_BASE_URL": "http://127.0.0.1:18789",
                "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "OPENCLAW_HOOKS_PATH": "/hooks",
                "OPENCLAW_AGENT_ID": "hooks",
                "OPENCLAW_SESSION_KEY": "hook:harness",
                "OPENCLAW_WAKE_MODE": "now",
                "OPENCLAW_OWNER": "harness-bridge",
                "USERPROFILE": str(self.base),
            },
        )

        self.assertEqual("https://dev.azure.com/example-org", config.azure_devops.base_url)
        self.assertEqual("ExampleProject", config.azure_devops.project)
        self.assertEqual("rocketchat-webhook", config.rocketchat.mode)
        self.assertEqual("codex-acp", config.executor.mode)
        self.assertEqual("ai", config.runtime.branch_prefix)
        self.assertEqual("http://127.0.0.1:18789", config.openclaw_hooks.base_url)
        self.assertEqual("gateway-secret", config.openclaw_gateway_token)
        self.assertEqual("/hooks", config.openclaw_hooks.path)
        self.assertEqual("hooks", config.openclaw_hooks.agent_id)
        self.assertEqual("hook:harness", config.openclaw_hooks.default_session_key)
        self.assertEqual("now", config.openclaw_hooks.wake_mode)
        self.assertEqual("harness-bridge", config.owner)

    def test_handle_task_event_claims_run_and_dispatches_openclaw(self) -> None:
        result = self.bridge.handle_ado_event(
            event_type="task.created",
            source_id="evt-1",
            payload={
                "resource": {
                    "id": 123,
                    "fields": {"System.TeamProject": "AB"},
                    "repository": {"id": "repo-1"},
                    "revisedBy": {"id": "user-1", "displayName": "Alice"},
                }
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("task_dispatched", result.action)
        run = self.store.get_run("run-1")
        self.assertIsNotNone(run)
        self.assertEqual("planning", run.status)

        hook_call = self.openclaw_transport.calls[0]
        self.assertIn("/hooks/agent", hook_call["url"])
        hook_payload = json.loads(hook_call["body"].decode("utf-8"))
        self.assertEqual("hooks", hook_payload["agentId"])
        self.assertEqual("hook:harness:task:AB-123", hook_payload["sessionKey"])

        notify_call = self.chat_transport.calls[0]
        payload = json.loads(notify_call["body"].decode("utf-8"))
        self.assertEqual("Task AB#123 claimed and dispatched to OpenClaw", payload["text"])

    def test_handle_task_event_queues_background_orchestration_when_configured(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-async-1",
        )

        result = bridge.handle_ado_event(
            event_type="task.created",
            source_id="evt-async-1",
            payload={
                "resource": {
                    "id": 124,
                    "fields": {"System.TeamProject": "AB"},
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertTrue(result.accepted)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("run-async-1", task_orchestrator.calls[0]["run_id"])
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-async-1")]
        self.assertIn("task_run_queued", audit_events)
        self.assertEqual([], self.openclaw_transport.calls)

    def test_duplicate_task_event_is_rejected(self) -> None:
        first = self.bridge.handle_ado_event(
            event_type="task.created",
            source_id="evt-1",
            payload={"resource": {"id": 123, "fields": {"System.TeamProject": "AB"}}},
        )
        second = self.bridge.handle_ado_event(
            event_type="task.created",
            source_id="evt-1",
            payload={"resource": {"id": 123, "fields": {"System.TeamProject": "AB"}}},
        )

        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual("already_claimed", second.reason)

    def test_task_event_continues_when_chat_notification_fails(self) -> None:
        self.chat_transport.responses.append(
            (
                400,
                {"Content-Type": "application/json"},
                b'{"success":false,"error":"channel override disabled"}',
            )
        )

        result = self.bridge.handle_ado_event(
            event_type="task.created",
            source_id="evt-chat-fail-1",
            payload={"resource": {"id": 456, "fields": {"System.TeamProject": "AB"}}},
        )

        self.assertTrue(result.accepted)
        self.assertEqual("task_dispatched", result.action)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-1")]
        self.assertEqual(["run_claimed", "status_transition", "openclaw_dispatch", "notification_failed"], audit_events)

    def test_pr_event_queues_existing_run_into_runtime_orchestrator(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-pr-1",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-2",
                provider_type="azure-devops",
                task_id="123",
                task_key="AB#123",
                repo_id="repo-1",
                pr_id="42",
                session_id="hook:harness:task:AB-123",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )
        self.ado_transport.responses.clear()
        self.ado_transport.queue_json(
            {
                "value": [
                    {
                        "id": 8,
                        "status": "active",
                        "comments": [{"id": 1, "content": "please fix"}],
                    }
                ]
            }
        )

        result = bridge.handle_ado_event(
            event_type="pr.comment.created",
            source_id="evt-pr-1",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("pr_feedback_queued", result.action)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("resume_from_pr_feedback", task_orchestrator.calls[0]["method"])
        self.assertEqual("run-2", task_orchestrator.calls[0]["run_id"])
        self.assertEqual(1, len(task_orchestrator.calls[0]["comments"]))
        self.assertEqual("pr.comment.created", task_orchestrator.calls[0]["event_payload"]["event_type"])
        run = self.store.get_run("run-2")
        self.assertEqual("awaiting_review", run.status)
        self.assertEqual([], self.openclaw_transport.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-2")]
        self.assertIn("pr_feedback_queued", audit_events)

    def test_ci_event_queues_existing_run_into_runtime_orchestrator_and_notifies(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-ci-1",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-3",
                provider_type="azure-devops",
                task_id="123",
                task_key="AB#123",
                ci_run_id="99",
                session_id="hook:harness:task:AB-123",
                executor_type="codex-acp",
                status="awaiting_ci",
            )
        )
        self.ado_transport.responses.clear()
        self.ado_transport.queue_json(
            {
                "id": 99,
                "status": "completed",
                "result": "failed",
                "definition": {"id": 7},
            }
        )

        result = bridge.handle_ado_event(
            event_type="ci.run.failed",
            source_id="evt-ci-1",
            payload={
                "resource": {
                    "buildId": 99,
                    "status": "completed",
                    "result": "failed",
                }
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("ci_recovery_queued", result.action)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("resume_from_ci_failure", task_orchestrator.calls[0]["method"])
        self.assertEqual("run-3", task_orchestrator.calls[0]["run_id"])
        self.assertEqual("ci.run.failed", task_orchestrator.calls[0]["event_payload"]["event_type"])
        self.assertEqual(99, task_orchestrator.calls[0]["build_summary"]["id"])
        run = self.store.get_run("run-3")
        self.assertEqual("awaiting_ci", run.status)
        self.assertEqual([], self.openclaw_transport.calls)
        notify_payload = json.loads(self.chat_transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual("CI failure for AB#123 queued for recovery", notify_payload["text"])
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-3")]
        self.assertIn("ci_recovery_queued", audit_events)


if __name__ == "__main__":
    unittest.main()
