from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

import harness_runtime.main as harness_main
from ado_client import AzureDevOpsRestClient
from github_client import GitHubRestClient
from harness_runtime import (
    HarnessBridge,
    ImageAnalysisError,
    ImageAnalysisResult,
    OpenClawWebhookClient,
    TaskRunOrchestrator,
    load_harness_runtime_config,
)
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


class BlockingTaskOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.started = threading.Event()
        self.release = threading.Event()

    def run_claimed_task(self, run_id: str, *, task_context: dict[str, object]) -> None:
        self.calls.append({"method": "run_claimed_task", "run_id": run_id, "task_context": task_context})
        self.started.set()
        self.release.wait(2.0)

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
        self.started.set()
        self.release.wait(2.0)

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
        self.started.set()
        self.release.wait(2.0)


class RecordingImageAnalyzer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def analyze(
        self,
        *,
        context_text: str,
        attachment: dict[str, object],
        task_key: str | None = None,
    ) -> ImageAnalysisResult:
        self.calls.append(
            {
                "context_text": context_text,
                "attachment": dict(attachment),
                "task_key": task_key,
            }
        )
        return ImageAnalysisResult(
            model="gpt-5.4",
            summary="图片中主按钮缺失，疑似被权限开关或条件渲染隐藏，建议先检查前端权限判断和最近的 UI 开关配置。",
            response_id="resp-image-1",
        )


class FailingImageAnalyzer:
    def analyze(
        self,
        *,
        context_text: str,
        attachment: dict[str, object],
        task_key: str | None = None,
    ) -> ImageAnalysisResult:
        del context_text, attachment, task_key
        raise ImageAnalysisError("upstream vision endpoint unavailable")


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
    command_token_env: RC_COMMAND_TOKEN
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
                "RC_COMMAND_TOKEN": "chat-command-secret",
                "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "HARNESS_INGRESS_TOKEN": "ingress-secret",
            },
        )
        self.store = RunStore(self.config.runtime.sqlite_path)
        self.store.initialize()

        self.ado_transport = RecordingTransport()
        self.github_transport = RecordingTransport()
        self.openclaw_transport = RecordingTransport()
        self.chat_transport = RecordingTransport()

        self.ado_transport.queue_json({"id": 123, "fields": {"System.Title": "Fix bug"}})
        self.ado_client = AzureDevOpsRestClient(
            base_url=self.config.azure_devops.base_url,
            project=self.config.azure_devops.project,
            pat=self.config.azure_devops.pat,
            transport=self.ado_transport,
        )
        self.github_client = GitHubRestClient(
            token="github-secret",
            transport=self.github_transport,
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
            github_client=self.github_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            run_id_factory=lambda: "run-1",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def wait_for_follow_up_lock_release(self, lock_key: str, run_id: str) -> None:
        for _ in range(100):
            result = self.store.acquire_lock(
                lock_key,
                run_id=run_id,
                owner=self.config.owner,
                ttl_seconds=self.config.runtime.lock_ttl_seconds,
            )
            if result.acquired:
                self.store.release_lock(lock_key, owner=self.config.owner)
                return
            time.sleep(0.01)
        self.fail(f"Timed out waiting for lock release: {lock_key}")

    def make_chat_control_bridge(self) -> HarnessBridge:
        return HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=TaskRunOrchestrator(
                config=self.config,
                store=self.store,
                ado_client=self.ado_client,
                executor_runner=object(),
                notifier=self.notifier,
            ),
            run_id_factory=lambda: "run-chat-control",
        )

    def make_image_bridge(self, image_analyzer: RecordingImageAnalyzer) -> HarnessBridge:
        return HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            image_analyzer=image_analyzer,
            run_id_factory=lambda: "run-image-bridge",
        )

    def test_load_harness_runtime_config_resolves_secrets(self) -> None:
        self.assertEqual("ado-secret", self.config.azure_devops.pat)
        self.assertEqual("https://chat.example/hooks/1/abc", self.config.rocketchat.webhook_url)
        self.assertEqual("chat-command-secret", self.config.rocketchat.command_token)
        self.assertEqual("gateway-secret", self.config.openclaw_gateway_token)
        self.assertEqual("hook-secret", self.config.openclaw_hooks.token)
        self.assertEqual("ingress-secret", self.config.ingress_token)
        self.assertIsNone(self.config.readonly_token)
        self.assertIsNone(self.config.control_token)

    def test_load_harness_runtime_config_resolves_readonly_token(self) -> None:
        config = load_harness_runtime_config(
            providers_path=self.base / "providers.yaml",
            policy_path=self.base / "harness-policy.yaml",
            openclaw_path=self.base / "openclaw.json",
            env={
                "ADO_PAT": "ado-secret",
                "ADO_WEBHOOK_SECRET": "ado-webhook",
                "RC_WEBHOOK_URL": "https://chat.example/hooks/1/abc",
                "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "HARNESS_INGRESS_TOKEN": "ingress-secret",
                "HARNESS_READONLY_TOKEN": "readonly-secret",
            },
        )

        self.assertEqual("readonly-secret", config.readonly_token)
        self.assertIsNone(config.control_token)

    def test_load_harness_runtime_config_resolves_control_token(self) -> None:
        config = load_harness_runtime_config(
            providers_path=self.base / "providers.yaml",
            policy_path=self.base / "harness-policy.yaml",
            openclaw_path=self.base / "openclaw.json",
            env={
                "ADO_PAT": "ado-secret",
                "ADO_WEBHOOK_SECRET": "ado-webhook",
                "RC_WEBHOOK_URL": "https://chat.example/hooks/1/abc",
                "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "HARNESS_INGRESS_TOKEN": "ingress-secret",
                "HARNESS_CONTROL_TOKEN": "control-secret",
            },
        )

        self.assertEqual("control-secret", config.control_token)

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

    def test_legacy_acpx_backend_maps_to_codex_acp_capability(self) -> None:
        self.assertEqual("codex-acp", harness_main._resolve_executor_capability_id(self.config))

    def test_load_harness_runtime_config_supports_nested_provider_configs(self) -> None:
        providers_path = self.base / "providers-multi.yaml"
        providers_path.write_text(
            """
providers:
  task_pr_ci:
    default_provider: github
    azure_devops:
      family: azure-devops
      mode: ado-rest
      base_url: https://dev.azure.com/example-org
      project: ExampleProject
      auth:
        type: pat
        secret_env: ADO_PAT
      events:
        webhook_secret_env: ADO_WEBHOOK_SECRET
    github:
      family: github
      mode: github-rest
      base_url: https://api.github.com
      auth:
        type: token
        secret_env: GITHUB_TOKEN
      events:
        webhook_secret_env: GITHUB_WEBHOOK_SECRET
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
    path: DB_PATH
  workspace_root: D:/Repos/workspaces
  branch_prefix: ai
""".replace("DB_PATH", str(self.base / "nested.db").replace("\\", "/")),
            encoding="utf-8",
        )

        config = load_harness_runtime_config(
            providers_path=providers_path,
            policy_path=self.base / "harness-policy.yaml",
            openclaw_path=self.base / "openclaw.json",
            env={
                "ADO_PAT": "ado-secret",
                "ADO_WEBHOOK_SECRET": "ado-webhook",
                "GITHUB_TOKEN": "github-token",
                "GITHUB_WEBHOOK_SECRET": "github-webhook",
                "RC_WEBHOOK_URL": "https://chat.example/hooks/1/abc",
                "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "HARNESS_INGRESS_TOKEN": "ingress-secret",
            },
        )

        self.assertEqual("github", config.default_task_provider)
        self.assertEqual("https://dev.azure.com/example-org", config.azure_devops.base_url)
        self.assertEqual("ado-webhook", config.azure_devops.webhook_secret)
        self.assertEqual("https://api.github.com", config.github.base_url)
        self.assertEqual("github-token", config.github.token)
        self.assertEqual("github-webhook", config.github.webhook_secret)

    def test_load_harness_runtime_config_supports_local_task_provider(self) -> None:
        providers_path = self.base / "providers-local.yaml"
        providers_path.write_text(
            """
providers:
  task_pr_ci:
    family: local-task
    mode: local-file
    repository_path: ${LOCAL_REPO_PATH}
    task_directory: ${LOCAL_TASKS_PATH}
    review_directory: ${LOCAL_REVIEW_PATH}
    base_branch: ${LOCAL_BASE_BRANCH}
    push_enabled: ${LOCAL_PUSH_ENABLED}
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
    path: DB_PATH
  workspace_root: D:/Repos/workspaces
  branch_prefix: ai
""".replace("DB_PATH", str(self.base / "local.db").replace("\\", "/")),
            encoding="utf-8",
        )

        config = load_harness_runtime_config(
            providers_path=providers_path,
            policy_path=self.base / "harness-policy.yaml",
            openclaw_path=self.base / "openclaw.json",
            env={
                "LOCAL_REPO_PATH": str(self.base / "repo"),
                "LOCAL_TASKS_PATH": str(self.base / "tasks"),
                "LOCAL_REVIEW_PATH": str(self.base / "reviews"),
                "LOCAL_BASE_BRANCH": "main",
                "LOCAL_PUSH_ENABLED": "1",
                "RC_WEBHOOK_URL": "https://chat.example/hooks/1/abc",
                "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                "OPENCLAW_HOOKS_TOKEN": "hook-secret",
                "HARNESS_INGRESS_TOKEN": "ingress-secret",
            },
        )

        self.assertEqual("local-task", config.default_task_provider)
        self.assertEqual("local-file", config.local_task.mode)
        self.assertEqual(str(self.base / "repo"), config.local_task.repository_path)
        self.assertEqual(str(self.base / "tasks"), config.local_task.task_directory)
        self.assertEqual(str(self.base / "reviews"), config.local_task.review_directory)
        self.assertEqual("main", config.local_task.base_branch)
        self.assertTrue(config.local_task.push_enabled)

    def test_load_harness_runtime_config_allows_core_only_mode_without_openclaw_file(self) -> None:
        providers_path = self.base / "providers-core-only.yaml"
        providers_path.write_text(
            """
providers:
  task_pr_ci:
    default_provider: local-task
    local_task:
      family: local-task
      mode: local-file
      repository_path: ${LOCAL_REPO_PATH}
      task_directory: ${LOCAL_TASKS_PATH}
      review_directory: ${LOCAL_REVIEW_PATH}
      push_enabled: false
  chat:
    family: rocketchat
    mode: disabled
    webhook_url_env: RC_WEBHOOK_URL
  executor:
    family: codex
    mode: codex-cli
    harness: codex
    backend: codex-cli
    runtime:
      timeout_seconds: 3600
runtime:
  shell:
    enabled: false
  storage:
    kind: sqlite
    path: DB_PATH
  workspace_root: D:/Repos/workspaces
  branch_prefix: ai
  owner: harness-core
""".replace("DB_PATH", str(self.base / "core-only.db").replace("\\", "/")),
            encoding="utf-8",
        )

        config = load_harness_runtime_config(
            providers_path=providers_path,
            policy_path=self.base / "harness-policy.yaml",
            openclaw_path=self.base / "missing-openclaw.json",
            env={
                "LOCAL_REPO_PATH": str(self.base / "repo"),
                "LOCAL_TASKS_PATH": str(self.base / "tasks"),
                "LOCAL_REVIEW_PATH": str(self.base / "reviews"),
                "HARNESS_INGRESS_TOKEN": "ingress-secret",
            },
        )

        self.assertFalse(config.shell_enabled)
        self.assertIsNone(config.openclaw_hooks)
        self.assertIsNone(config.openclaw_gateway_token)
        self.assertEqual("ingress-secret", config.ingress_token)
        self.assertEqual("harness-core", config.owner)
        self.assertEqual("local-task", config.default_task_provider)

    def test_handle_chat_command_returns_status_by_run_id_and_links_conversation(self) -> None:
        run = self.store.create_run(
            TaskRun(
                run_id="run-chat-status",
                provider_type="azure-devops",
                task_id="900",
                task_key="AB#900",
                repo_id="repo-1",
                branch_name="ai/900",
                pr_id="42",
                ci_run_id="99",
                session_id="session-chat-status",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )

        result = self.bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "status run-chat-status",
                "tmid": "thread-status",
                "user_name": "alice",
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual("status", result.command)
        self.assertEqual(run.run_id, result.run_id)
        self.assertIn("AB#900 当前状态：awaiting_review", result.text)
        self.assertEqual("thread-status", self.store.get_run(run.run_id).chat_thread_id)
        self.assertEqual(run.run_id, self.store.get_thread_link("thread-status")["run_id"])
        audit_events = [entry["event_type"] for entry in self.store.list_audit(run.run_id)]
        self.assertIn("chat_thread_linked", audit_events)
        self.assertIn("chat_command_received", audit_events)

    def test_handle_chat_command_returns_detail_by_task_key(self) -> None:
        run = self.store.create_run(
            TaskRun(
                run_id="run-chat-detail",
                provider_type="azure-devops",
                task_id="901",
                task_key="AB#901",
                repo_id="repo-1",
                session_id="session-chat-detail",
                executor_type="codex-acp",
                status="awaiting_ci",
                workspace_path="/tmp/run-chat-detail",
            )
        )
        self.store.append_audit(run.run_id, "executor_completed", payload={"summary": "Implemented patch"})
        self.store.record_checkpoint(run.run_id, "verification", payload={"check_count": 2})

        result = self.bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "details AB#901",
                "channel_id": "room-detail",
                "user_name": "bob",
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual("detail", result.command)
        self.assertIn("AB#901 / root run-chat-detail / awaiting_ci", result.text)
        self.assertIn("最近事件：executor_completed, chat_thread_linked, chat_command_received", result.text)
        self.assertIn("最近检查点：verification", result.text)

    def test_handle_chat_command_pause_and_resume_restore_previous_statuses(self) -> None:
        chat_bridge = self.make_chat_control_bridge()
        root = self.store.create_run(
            TaskRun(
                run_id="run-chat-root",
                provider_type="azure-devops",
                task_id="902",
                task_key="AB#902",
                repo_id="repo-1",
                session_id="session-chat-root",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )
        child = self.store.create_run(
            TaskRun(
                run_id="run-chat-child",
                provider_type="azure-devops",
                task_id="902",
                task_key="AB#902",
                repo_id="repo-1",
                session_id="session-chat-child",
                executor_type="codex-acp",
                status="coding",
            )
        )
        self.store.link_runs(root.run_id, child.run_id, relation_type="agent-executor")

        paused = chat_bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "pause run-chat-child waiting for product answer",
                "tmid": "thread-pause",
                "user_name": "carol",
            },
        )

        self.assertTrue(paused.ok)
        self.assertIn("运行已暂停。", paused.text)
        self.assertEqual("awaiting_human", self.store.get_run(root.run_id).status)
        self.assertEqual("awaiting_human", self.store.get_run(child.run_id).status)
        self.assertEqual("thread-pause", self.store.get_thread_link("thread-pause")["chat_thread_id"])
        self.assertEqual("chat_pause", self.store.list_checkpoints(child.run_id)[0]["stage"])

        resumed = chat_bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "resume run-chat-child",
                "tmid": "thread-pause",
                "user_name": "carol",
            },
        )

        self.assertTrue(resumed.ok)
        self.assertIn("运行已恢复。", resumed.text)
        self.assertEqual("awaiting_review", self.store.get_run(root.run_id).status)
        self.assertEqual("coding", self.store.get_run(child.run_id).status)
        self.assertIsNone(self.store.get_run(root.run_id).last_error)
        self.assertIsNone(self.store.get_run(child.run_id).last_error)
        child_audit = [entry["event_type"] for entry in self.store.list_audit(child.run_id)]
        root_audit = [entry["event_type"] for entry in self.store.list_audit(root.run_id)]
        self.assertIn("chat_command_applied", child_audit)
        self.assertIn("chat_command_applied", root_audit)

    def test_handle_chat_command_supports_bot_view_payload_shape(self) -> None:
        chat_bridge = self.make_chat_control_bridge()
        run = self.store.create_run(
            TaskRun(
                run_id="run-bot-view",
                provider_type="azure-devops",
                task_id="9021",
                task_key="AB#9021",
                repo_id="repo-1",
                session_id="session-bot-view",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )

        paused = chat_bridge.handle_chat_command(
            provider_type="bot-view",
            payload={
                "command": "pause",
                "run_id": run.run_id,
                "reason": "bot-view operator pause",
                "user_label": "bot-view",
            },
        )
        self.assertTrue(paused.ok)
        self.assertEqual("awaiting_human", self.store.get_run(run.run_id).status)

        resumed = chat_bridge.handle_chat_command(
            provider_type="bot-view",
            payload={
                "command": "resume",
                "run_id": run.run_id,
                "user_label": "bot-view",
            },
        )
        self.assertTrue(resumed.ok)
        self.assertEqual("awaiting_review", self.store.get_run(run.run_id).status)

    def test_handle_chat_command_supports_weixin_payload_shape(self) -> None:
        run = self.store.create_run(
            TaskRun(
                run_id="run-weixin-status",
                provider_type="azure-devops",
                task_id="9051",
                task_key="AB#9051",
                repo_id="repo-1",
                session_id="session-weixin-status",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )

        result = self.bridge.handle_chat_command(
            provider_type="weixin",
            payload={
                "command": "status",
                "task_key": run.task_key,
                "conversation_id": "wx-room-1",
                "user_id": "wx-operator",
            },
        )

        self.assertTrue(result.ok)
        self.assertIn("AB#9051 当前状态：awaiting_review", result.text)
        self.assertEqual(run.run_id, self.store.get_thread_link("wx-room-1")["run_id"])

    def test_handle_chat_command_add_context_records_artifacts_and_attachments(self) -> None:
        root = self.store.create_run(
            TaskRun(
                run_id="run-chat-context-root",
                provider_type="azure-devops",
                task_id="903",
                task_key="AB#903",
                repo_id="repo-1",
                session_id="session-chat-context-root",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )
        child = self.store.create_run(
            TaskRun(
                run_id="run-chat-context-child",
                provider_type="azure-devops",
                task_id="903",
                task_key="AB#903",
                repo_id="repo-1",
                session_id="session-chat-context-child",
                executor_type="codex-acp",
                status="coding",
            )
        )
        self.store.link_runs(root.run_id, child.run_id, relation_type="agent-executor")

        result = self.bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "add-context run-chat-context-child 截图里按钮丢失，优先排查权限控制",
                "tmid": "thread-context",
                "user_name": "dora",
                "attachments": [
                    {
                        "title": "screenshot",
                        "image_url": "https://example.invalid/screenshot.png",
                        "contentType": "image/png",
                    }
                ],
                "files": [
                    {
                        "name": "build.log",
                        "mime": "text/plain",
                        "url": "https://example.invalid/build.log",
                    }
                ],
            },
        )

        self.assertTrue(result.ok)
        self.assertIn("上下文已追加。", result.text)
        child_artifact_types = [item["artifact_type"] for item in self.store.list_artifacts(child.run_id)]
        root_artifact_types = [item["artifact_type"] for item in self.store.list_artifacts(root.run_id)]
        self.assertIn("chat-context", child_artifact_types)
        self.assertIn("chat-image", child_artifact_types)
        self.assertIn("chat-attachment", child_artifact_types)
        self.assertIn("chat-context", root_artifact_types)
        root_context = next(item for item in self.store.list_artifacts(root.run_id) if item["artifact_type"] == "chat-context")
        self.assertEqual(child.run_id, json.loads(root_context["payload_json"])["target_run_id"])
        child_audit = [entry["event_type"] for entry in self.store.list_audit(child.run_id)]
        self.assertIn("chat_context_added", child_audit)

    def test_handle_chat_command_add_context_analyzes_image_and_records_evidence(self) -> None:
        image_analyzer = RecordingImageAnalyzer()
        bridge = self.make_image_bridge(image_analyzer)
        run = self.store.create_run(
            TaskRun(
                run_id="run-chat-image",
                provider_type="azure-devops",
                task_id="9031",
                task_key="AB#9031",
                repo_id="repo-1",
                session_id="session-chat-image",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )

        result = bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "add-context run-chat-image 请结合截图判断为什么入口按钮消失",
                "tmid": "thread-image",
                "user_name": "gina",
                "attachments": [
                    {
                        "title": "bug-screenshot",
                        "image_url": "https://example.invalid/bug.png",
                        "contentType": "image/png",
                    }
                ],
            },
        )

        self.assertTrue(result.ok)
        self.assertEqual(1, len(image_analyzer.calls))
        self.assertIn("图片分析：图片中主按钮缺失", result.text)
        image_artifacts = self.store.list_artifacts(run.run_id, artifact_type="image-analysis")
        self.assertEqual(1, len(image_artifacts))
        image_payload = json.loads(image_artifacts[0]["payload_json"])
        self.assertEqual("gpt-5.4", image_payload["model"])
        self.assertEqual("resp-image-1", image_payload["response_id"])
        self.assertIn("主按钮缺失", image_payload["summary"])
        audit_events = [entry["event_type"] for entry in self.store.list_audit(run.run_id)]
        self.assertIn("image_analysis_completed", audit_events)
        self.assertEqual("image_analysis", self.store.list_checkpoints(run.run_id)[-1]["stage"])

    def test_handle_chat_command_add_context_keeps_command_successful_when_image_analysis_fails(self) -> None:
        bridge = self.make_image_bridge(FailingImageAnalyzer())
        run = self.store.create_run(
            TaskRun(
                run_id="run-chat-image-fail",
                provider_type="azure-devops",
                task_id="9032",
                task_key="AB#9032",
                repo_id="repo-1",
                session_id="session-chat-image-fail",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )

        result = bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "add-context run-chat-image-fail 这张图里有异常，请继续记录上下文",
                "tmid": "thread-image-fail",
                "user_name": "helen",
                "attachments": [
                    {
                        "title": "bug-screenshot",
                        "image_url": "https://example.invalid/bug-fail.png",
                        "contentType": "image/png",
                    }
                ],
            },
        )

        self.assertTrue(result.ok)
        self.assertIn("上下文已追加。", result.text)
        self.assertNotIn("图片分析：", result.text)
        self.assertEqual([], self.store.list_artifacts(run.run_id, artifact_type="image-analysis"))
        audit_entries = self.store.list_audit(run.run_id)
        self.assertIn("image_analysis_failed", [entry["event_type"] for entry in audit_entries])
        failure_payload = json.loads(next(entry for entry in audit_entries if entry["event_type"] == "image_analysis_failed")["payload_json"])
        self.assertEqual("upstream vision endpoint unavailable", failure_payload["error"])

    def test_handle_chat_command_escalate_blocks_root_and_child_runs(self) -> None:
        chat_bridge = self.make_chat_control_bridge()
        root = self.store.create_run(
            TaskRun(
                run_id="run-chat-escalate-root",
                provider_type="azure-devops",
                task_id="904",
                task_key="AB#904",
                repo_id="repo-1",
                session_id="session-chat-escalate-root",
                executor_type="codex-acp",
                status="awaiting_ci",
            )
        )
        child = self.store.create_run(
            TaskRun(
                run_id="run-chat-escalate-child",
                provider_type="azure-devops",
                task_id="904",
                task_key="AB#904",
                repo_id="repo-1",
                session_id="session-chat-escalate-child",
                executor_type="codex-acp",
                status="coding",
            )
        )
        self.store.link_runs(root.run_id, child.run_id, relation_type="ci-recovery")

        result = chat_bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "escalate run-chat-escalate-child manual approval required",
                "tmid": "thread-escalate",
                "user_name": "erin",
            },
        )

        self.assertTrue(result.ok)
        self.assertIn("运行已升级为人工介入。", result.text)
        self.assertEqual("awaiting_human", self.store.get_run(root.run_id).status)
        self.assertEqual("awaiting_human", self.store.get_run(child.run_id).status)
        self.assertEqual("manual approval required", self.store.get_run(root.run_id).last_error)
        child_pause = next(
            item for item in self.store.list_checkpoints(child.run_id)
            if item["stage"] == "chat_pause"
        )
        self.assertEqual("escalate", json.loads(child_pause["payload_json"])["command"])
        root_audit = [entry["event_type"] for entry in self.store.list_audit(root.run_id)]
        child_audit = [entry["event_type"] for entry in self.store.list_audit(child.run_id)]
        self.assertIn("child_run_blocked", root_audit)
        self.assertIn("run_blocked", child_audit)

    def test_handle_chat_command_can_resolve_target_from_linked_conversation(self) -> None:
        run = self.store.create_run(
            TaskRun(
                run_id="run-chat-thread",
                provider_type="azure-devops",
                task_id="905",
                task_key="AB#905",
                repo_id="repo-1",
                session_id="session-chat-thread",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )

        first = self.bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "status run-chat-thread",
                "tmid": "thread-linked",
                "user_name": "frank",
            },
        )
        second = self.bridge.handle_chat_command(
            provider_type="rocketchat",
            payload={
                "text": "detail",
                "tmid": "thread-linked",
                "user_name": "frank",
            },
        )

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(run.run_id, second.run_id)
        self.assertIn("AB#905 / root run-chat-thread / awaiting_review", second.text)

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
            github_client=self.github_client,
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
        notify_payload = json.loads(self.chat_transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual("Task AB#124 claimed and queued for ClawHarness orchestration", notify_payload["text"])

    def test_handle_task_event_in_core_only_mode_uses_fallback_session_key(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        core_only_config = replace(
            self.config,
            openclaw_hooks=None,
            openclaw_gateway_token=None,
            shell_enabled=False,
        )
        bridge = HarnessBridge(
            config=core_only_config,
            store=self.store,
            ado_client=self.ado_client,
            github_client=self.github_client,
            openclaw_client=None,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-core-only-task",
        )

        result = bridge.handle_ado_event(
            event_type="task.created",
            source_id="evt-core-only-1",
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
        self.assertTrue(task_orchestrator.event.wait(1.0))
        run = self.store.get_run("run-core-only-task")
        self.assertIsNotNone(run)
        self.assertEqual("core:harness-bridge:task:AB-123", run.session_id)
        notify_payload = json.loads(self.chat_transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual("Task AB#123 claimed and queued for ClawHarness orchestration", notify_payload["text"])

    def test_github_issue_event_queues_background_orchestration(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            github_client=self.github_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-gh-task",
        )
        self.github_transport.queue_json(
            {
                "number": 456,
                "title": "Implement GitHub provider",
                "body": "Need to drive the same task loop from GitHub issues.",
                "state": "open",
                "html_url": "https://github.com/lusipad/ClawHarness/issues/456",
            }
        )

        result = bridge.handle_github_event(
            event_type="issues",
            source_id="gh-evt-1",
            payload={
                "action": "opened",
                "issue": {"number": 456, "title": "Implement GitHub provider"},
                "repository": {"full_name": "lusipad/ClawHarness"},
                "sender": {"login": "alice", "id": 7},
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("task_dispatched", result.action)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("run_claimed_task", task_orchestrator.calls[0]["method"])
        self.assertEqual("run-gh-task", task_orchestrator.calls[0]["run_id"])
        run = self.store.get_run("run-gh-task")
        self.assertEqual("github", run.provider_type)
        self.assertEqual("lusipad/ClawHarness", run.repo_id)
        self.assertEqual("lusipad/ClawHarness#456", run.task_key)

    def test_github_pr_comment_event_queues_existing_run(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            github_client=self.github_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-gh-pr",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-gh-pr-parent",
                provider_type="github",
                task_id="456",
                task_key="lusipad/ClawHarness#456",
                repo_id="lusipad/ClawHarness",
                pr_id="42",
                session_id="hook:harness:task:gh-456",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )
        self.github_transport.queue_json(
            [
                {
                    "id": 31,
                    "body": "please adjust the summary",
                    "created_at": "2026-04-05T12:00:00Z",
                    "updated_at": "2026-04-05T12:00:00Z",
                    "user": {"login": "reviewer"},
                }
            ]
        )
        self.github_transport.queue_json([])

        result = bridge.handle_github_event(
            event_type="pull_request_review_comment",
            source_id="gh-pr-comment-1",
            payload={
                "action": "created",
                "pull_request": {"number": 42},
                "repository": {"full_name": "lusipad/ClawHarness"},
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("pr_feedback_queued", result.action)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("resume_from_pr_feedback", task_orchestrator.calls[0]["method"])
        self.assertEqual("run-gh-pr-parent", task_orchestrator.calls[0]["run_id"])
        self.assertEqual(1, len(task_orchestrator.calls[0]["comments"]))
        self.wait_for_follow_up_lock_release("followup:run-gh-pr-parent:pr-feedback", "run-gh-pr-parent")

    def test_github_ci_failure_binds_parent_run_from_pr_when_ci_id_is_new(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            github_client=self.github_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-gh-ci",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-gh-ci-parent",
                provider_type="github",
                task_id="456",
                task_key="lusipad/ClawHarness#456",
                repo_id="lusipad/ClawHarness",
                pr_id="42",
                session_id="hook:harness:task:gh-456",
                executor_type="codex-acp",
                status="awaiting_ci",
            )
        )
        self.github_transport.queue_json(
            {
                "id": 201,
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/lusipad/ClawHarness/runs/201",
            }
        )

        result = bridge.handle_github_event(
            event_type="check_run",
            source_id="gh-ci-1",
            payload={
                "action": "completed",
                "check_run": {
                    "id": 201,
                    "conclusion": "failure",
                    "pull_requests": [{"number": 42}],
                },
                "repository": {"full_name": "lusipad/ClawHarness"},
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("ci_recovery_queued", result.action)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("resume_from_ci_failure", task_orchestrator.calls[0]["method"])
        self.assertEqual("run-gh-ci-parent", task_orchestrator.calls[0]["run_id"])
        run = self.store.get_run("run-gh-ci-parent")
        self.assertEqual("check-run:201", run.ci_run_id)
        self.wait_for_follow_up_lock_release("followup:run-gh-ci-parent:ci-recovery", "run-gh-ci-parent")

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
        self.wait_for_follow_up_lock_release("followup:run-2:pr-feedback", "run-2")
        run = self.store.get_run("run-2")
        self.assertEqual("awaiting_review", run.status)
        self.assertEqual([], self.openclaw_transport.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-2")]
        self.assertIn("pr_feedback_queued", audit_events)

    def test_pr_event_requires_task_orchestrator_for_child_run_mode(self) -> None:
        self.store.create_run(
            TaskRun(
                run_id="run-pr-required",
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

        result = self.bridge.handle_ado_event(
            event_type="pr.comment.created",
            source_id="evt-pr-required",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual("task_orchestrator_required", result.reason)
        self.assertEqual([], self.openclaw_transport.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-pr-required")]
        self.assertIn("pr_feedback_rejected", audit_events)

    def test_ado_pr_merged_event_completes_existing_run_without_task_orchestrator(self) -> None:
        self.store.create_run(
            TaskRun(
                run_id="run-pr-merged",
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
        self.ado_transport.queue_json({"id": 123, "fields": {"System.State": "Done"}})
        self.ado_transport.queue_json({"id": 1, "text": "done"})

        result = self.bridge.handle_ado_event(
            event_type="git.pullrequest.updated",
            source_id="evt-pr-merged-1",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "status": "completed",
                    "mergeStatus": "succeeded",
                    "sourceRefName": "refs/heads/ai/task-1",
                    "targetRefName": "refs/heads/main",
                    "lastMergeCommit": {"commitId": "abc123"},
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("pr_completed", result.action)
        run = self.store.get_run("run-pr-merged")
        self.assertEqual("completed", run.status)
        self.assertEqual([], self.openclaw_transport.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-pr-merged")]
        self.assertIn("pr_completed", audit_events)
        self.assertIn("task_completion_synced", audit_events)
        self.assertEqual("PATCH", self.ado_transport.calls[0]["method"])
        self.assertEqual("POST", self.ado_transport.calls[1]["method"])
        notify_payload = json.loads(self.chat_transport.calls[0]["body"].decode("utf-8"))
        self.assertIn("PR 42 merged for AB#123", notify_payload["text"])

    def test_pr_event_rejects_when_follow_up_is_already_active(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-pr-locked",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-pr-locked",
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
        self.store.acquire_lock(
            "followup:run-pr-locked:pr-feedback",
            run_id="run-pr-locked",
            owner=self.config.owner,
            ttl_seconds=self.config.runtime.lock_ttl_seconds,
        )

        result = bridge.handle_ado_event(
            event_type="pr.comment.created",
            source_id="evt-pr-locked",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual("follow_up_already_active", result.reason)
        self.assertEqual([], task_orchestrator.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-pr-locked")]
        self.assertIn("pr_feedback_skipped", audit_events)

    def test_pr_event_lock_budget_outlives_runtime_lock_ttl(self) -> None:
        task_orchestrator = BlockingTaskOrchestrator()
        config = replace(
            self.config,
            runtime=replace(self.config.runtime, lock_ttl_seconds=1),
            executor=replace(self.config.executor, timeout_seconds=5),
        )
        bridge = HarnessBridge(
            config=config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-pr-budget",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-pr-budget",
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
        self.ado_transport.queue_json({"value": [{"id": 8, "status": "active", "comments": [{"id": 1, "content": "please fix"}]}]})
        self.ado_transport.queue_json({"value": [{"id": 9, "status": "active", "comments": [{"id": 2, "content": "please fix again"}]}]})

        first = bridge.handle_ado_event(
            event_type="pr.comment.created",
            source_id="evt-pr-budget-1",
            payload={"resource": {"pullRequestId": 42, "repository": {"id": "repo-1"}}},
        )
        self.assertTrue(first.accepted)
        self.assertTrue(task_orchestrator.started.wait(1.0))

        time.sleep(1.2)

        second = bridge.handle_ado_event(
            event_type="pr.comment.created",
            source_id="evt-pr-budget-2",
            payload={"resource": {"pullRequestId": 42, "repository": {"id": "repo-1"}}},
        )

        self.assertFalse(second.accepted)
        self.assertEqual("follow_up_already_active", second.reason)
        task_orchestrator.release.set()
        self.wait_for_follow_up_lock_release("followup:run-pr-budget:pr-feedback", "run-pr-budget")

    def test_pr_event_resolves_parent_run_and_deduplicates_replay(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-pr-parent",
        )
        parent = self.store.create_run(
            TaskRun(
                run_id="run-pr-parent",
                provider_type="azure-devops",
                task_id="123",
                task_key="AB#123",
                repo_id="repo-1",
                pr_id="42",
                session_id="parent-session",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )
        child = self.store.create_run(
            TaskRun(
                run_id="run-pr-child",
                provider_type="azure-devops",
                task_id="123",
                task_key="AB#123",
                repo_id="repo-1",
                pr_id="42",
                session_id="child-session",
                executor_type="codex-acp",
                status="completed",
            )
        )
        self.store.link_runs(parent.run_id, child.run_id, relation_type="pr-feedback")
        self.ado_transport.responses.clear()
        self.ado_transport.queue_json(
            {
                "value": [
                    {
                        "id": 8,
                        "status": "active",
                        "comments": [{"id": 1, "content": "please fix again"}],
                    }
                ]
            }
        )

        first = bridge.handle_ado_event(
            event_type="pr.comment.created",
            source_id="evt-pr-replay-1",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "repository": {"id": "repo-1"},
                }
            },
        )
        second = bridge.handle_ado_event(
            event_type="pr.comment.created",
            source_id="evt-pr-replay-1",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertTrue(first.accepted)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("run-pr-parent", task_orchestrator.calls[0]["run_id"])
        self.wait_for_follow_up_lock_release("followup:run-pr-parent:pr-feedback", "run-pr-parent")
        self.assertFalse(second.accepted)
        self.assertEqual("duplicate_event", second.reason)

    def test_github_pr_merged_event_completes_existing_run(self) -> None:
        self.store.create_run(
            TaskRun(
                run_id="run-gh-pr-merged",
                provider_type="github",
                task_id="456",
                task_key="lusipad/ClawHarness#456",
                repo_id="lusipad/ClawHarness",
                pr_id="42",
                session_id="hook:harness:task:gh-456",
                executor_type="codex-acp",
                status="awaiting_review",
            )
        )
        self.github_transport.responses.clear()
        self.github_transport.queue_json({"number": 456, "state": "closed"})
        self.github_transport.queue_json({"id": 70, "body": "done"})

        result = self.bridge.handle_github_event(
            event_type="pull_request",
            source_id="gh-pr-merged-1",
            payload={
                "action": "closed",
                "number": 42,
                "pull_request": {
                    "number": 42,
                    "merged": True,
                    "state": "closed",
                    "merge_commit_sha": "def456",
                    "head": {"ref": "ai/task-1"},
                    "base": {"ref": "main"},
                    "closed_at": "2026-04-08T00:00:00Z",
                },
                "repository": {"full_name": "lusipad/ClawHarness"},
                "sender": {"login": "octocat", "id": 7},
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("pr_completed", result.action)
        run = self.store.get_run("run-gh-pr-merged")
        self.assertEqual("completed", run.status)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-gh-pr-merged")]
        self.assertIn("pr_completed", audit_events)
        self.assertIn("task_completion_synced", audit_events)
        self.assertEqual("PATCH", self.github_transport.calls[0]["method"])
        self.assertEqual("POST", self.github_transport.calls[1]["method"])
        notify_payload = json.loads(self.chat_transport.calls[0]["body"].decode("utf-8"))
        self.assertIn("PR 42 merged for lusipad/ClawHarness#456", notify_payload["text"])

    def test_pr_merged_completion_sync_failure_does_not_block_run_completion(self) -> None:
        class FailingAzureClient(AzureDevOpsRestClient):
            def complete_task(self, work_item_id: int | str, *, repo_id: str | None = None, comment: str | None = None):
                del work_item_id, repo_id, comment
                raise RuntimeError("sync failed")

        failing_ado_client = FailingAzureClient(
            base_url=self.config.azure_devops.base_url,
            project=self.config.azure_devops.project,
            pat=self.config.azure_devops.pat,
            transport=self.ado_transport,
        )
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=failing_ado_client,
            github_client=self.github_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            run_id_factory=lambda: "run-1",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-pr-merged-sync-fail",
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

        result = bridge.handle_ado_event(
            event_type="git.pullrequest.updated",
            source_id="evt-pr-merged-sync-fail",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "status": "completed",
                    "mergeStatus": "succeeded",
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertTrue(result.accepted)
        self.assertEqual("completed", self.store.get_run("run-pr-merged-sync-fail").status)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-pr-merged-sync-fail")]
        self.assertIn("pr_completed", audit_events)
        self.assertIn("task_completion_sync_failed", audit_events)

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
        self.wait_for_follow_up_lock_release("followup:run-3:ci-recovery", "run-3")
        run = self.store.get_run("run-3")
        self.assertEqual("awaiting_ci", run.status)
        self.assertEqual([], self.openclaw_transport.calls)
        notify_payload = json.loads(self.chat_transport.calls[0]["body"].decode("utf-8"))
        self.assertEqual("CI failure for AB#123 queued for recovery", notify_payload["text"])
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-3")]
        self.assertIn("ci_recovery_queued", audit_events)

    def test_ci_event_requires_task_orchestrator_for_child_run_mode(self) -> None:
        self.store.create_run(
            TaskRun(
                run_id="run-ci-required",
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

        result = self.bridge.handle_ado_event(
            event_type="ci.run.failed",
            source_id="evt-ci-required",
            payload={
                "resource": {
                    "buildId": 99,
                    "status": "completed",
                    "result": "failed",
                }
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual("task_orchestrator_required", result.reason)
        self.assertEqual([], self.openclaw_transport.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-ci-required")]
        self.assertIn("ci_recovery_rejected", audit_events)

    def test_ci_event_rejects_when_follow_up_is_already_active(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-ci-locked",
        )
        self.store.create_run(
            TaskRun(
                run_id="run-ci-locked",
                provider_type="azure-devops",
                task_id="123",
                task_key="AB#123",
                ci_run_id="99",
                session_id="hook:harness:task:AB-123",
                executor_type="codex-acp",
                status="awaiting_ci",
            )
        )
        self.store.acquire_lock(
            "followup:run-ci-locked:ci-recovery",
            run_id="run-ci-locked",
            owner=self.config.owner,
            ttl_seconds=self.config.runtime.lock_ttl_seconds,
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
            source_id="evt-ci-locked",
            payload={
                "resource": {
                    "buildId": 99,
                    "status": "completed",
                    "result": "failed",
                }
            },
        )

        self.assertFalse(result.accepted)
        self.assertEqual("follow_up_already_active", result.reason)
        self.assertEqual([], task_orchestrator.calls)
        audit_events = [entry["event_type"] for entry in self.store.list_audit("run-ci-locked")]
        self.assertIn("ci_recovery_skipped", audit_events)

    def test_ci_event_resolves_parent_run_and_deduplicates_replay(self) -> None:
        task_orchestrator = RecordingTaskOrchestrator()
        bridge = HarnessBridge(
            config=self.config,
            store=self.store,
            ado_client=self.ado_client,
            openclaw_client=self.openclaw_client,
            notifier=self.notifier,
            task_orchestrator=task_orchestrator,
            run_id_factory=lambda: "run-ci-parent",
        )
        parent = self.store.create_run(
            TaskRun(
                run_id="run-ci-parent",
                provider_type="azure-devops",
                task_id="123",
                task_key="AB#123",
                ci_run_id="99",
                session_id="parent-session",
                executor_type="codex-acp",
                status="awaiting_ci",
            )
        )
        child = self.store.create_run(
            TaskRun(
                run_id="run-ci-child",
                provider_type="azure-devops",
                task_id="123",
                task_key="AB#123",
                ci_run_id="99",
                session_id="child-session",
                executor_type="codex-acp",
                status="completed",
            )
        )
        self.store.link_runs(parent.run_id, child.run_id, relation_type="ci-recovery")
        self.ado_transport.responses.clear()
        self.ado_transport.queue_json(
            {
                "id": 99,
                "status": "completed",
                "result": "failed",
                "definition": {"id": 7},
            }
        )

        first = bridge.handle_ado_event(
            event_type="ci.run.failed",
            source_id="evt-ci-replay-1",
            payload={
                "resource": {
                    "buildId": 99,
                    "status": "completed",
                    "result": "failed",
                }
            },
        )
        second = bridge.handle_ado_event(
            event_type="ci.run.failed",
            source_id="evt-ci-replay-1",
            payload={
                "resource": {
                    "buildId": 99,
                    "status": "completed",
                    "result": "failed",
                }
            },
        )

        self.assertTrue(first.accepted)
        self.assertTrue(task_orchestrator.event.wait(1.0))
        self.assertEqual("run-ci-parent", task_orchestrator.calls[0]["run_id"])
        self.wait_for_follow_up_lock_release("followup:run-ci-parent:ci-recovery", "run-ci-parent")
        self.assertFalse(second.accepted)
        self.assertEqual("duplicate_event", second.reason)


if __name__ == "__main__":
    unittest.main()
