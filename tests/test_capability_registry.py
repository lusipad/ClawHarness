from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ado_client import AzureDevOpsRestClient
from codex_acp_runner import CodexAcpRunner, CodexCliRunner
from github_client import GitHubRestClient
from local_client import LocalTaskClient
from rocketchat_notifier import RocketChatNotifier

from harness_runtime.capability_registry import (
    CapabilityRegistry,
    CapabilityRegistryError,
    default_capability_manifest_path,
    default_capability_manifest_paths,
    load_default_capability_registry,
    RuntimeCapabilityContext,
)
from harness_runtime.config import (
    ExecutorRuntimeConfig,
    HarnessRuntimeConfig,
    LocalTaskRuntimeConfig,
    OpenClawHooksConfig,
    RocketChatRuntimeConfig,
    RuntimeStorageConfig,
)


class CapabilityRegistryTests(unittest.TestCase):
    def test_load_default_capability_registry_exposes_builtin_task_providers(self) -> None:
        registry = load_default_capability_registry()

        task_providers = registry.capabilities_for("task-provider")
        executors = registry.capabilities_for("executor")
        notifiers = registry.capabilities_for("notifier")

        self.assertEqual(
            ["azure-devops", "github", "local-task"],
            [item.capability_id for item in task_providers],
        )
        self.assertEqual(["codex-acp", "codex-cli"], [item.capability_id for item in executors])
        self.assertEqual(["rocketchat-webhook"], [item.capability_id for item in notifiers])
        self.assertEqual(
            Path("harness_runtime") / "capabilities" / "builtin-task-providers.json",
            default_capability_manifest_path().relative_to(Path.cwd()),
        )
        self.assertEqual(
            [
                Path("harness_runtime") / "capabilities" / "builtin-executors.json",
                Path("harness_runtime") / "capabilities" / "builtin-notifiers.json",
                Path("harness_runtime") / "capabilities" / "builtin-task-providers.json",
            ],
            [path.relative_to(Path.cwd()) for path in default_capability_manifest_paths()],
        )

    def test_instantiate_task_providers_skips_disabled_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = HarnessRuntimeConfig(
                azure_devops=None,
                rocketchat=RocketChatRuntimeConfig(mode="disabled", webhook_url=None, channel=None),
                executor=ExecutorRuntimeConfig(mode="acp", harness="openclaw", backend="gateway", timeout_seconds=60),
                runtime=RuntimeStorageConfig(
                    sqlite_path=str(Path(temp_dir) / "runs.sqlite3"),
                    workspace_root=str(Path(temp_dir) / "workspace"),
                    branch_prefix="clawharness",
                    lock_ttl_seconds=60,
                    dedupe_ttl_seconds=60,
                ),
                openclaw_hooks=OpenClawHooksConfig(
                    base_url="http://127.0.0.1:18789",
                    token="token",
                    path="/hooks",
                    agent_id="agent",
                    default_session_key="default",
                    wake_mode="wake",
                ),
                openclaw_gateway_token=None,
                ingress_token=None,
                owner="owner",
                github=None,
                local_task=LocalTaskRuntimeConfig(
                    mode="local-task",
                    repository_path=temp_dir,
                    task_directory=temp_dir,
                    review_directory=temp_dir,
                    base_branch="main",
                    push_enabled=False,
                ),
                default_task_provider="local-task",
            )

            registry = load_default_capability_registry()
            providers = registry.instantiate_task_providers(config)

            self.assertEqual(["local-task"], list(providers))
            self.assertIsInstance(providers["local-task"], LocalTaskClient)

    def test_instantiate_task_providers_builds_expected_clients(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = HarnessRuntimeConfig(
                azure_devops=None,
                rocketchat=RocketChatRuntimeConfig(mode="disabled", webhook_url=None, channel=None),
                executor=ExecutorRuntimeConfig(mode="acp", harness="openclaw", backend="gateway", timeout_seconds=60),
                runtime=RuntimeStorageConfig(
                    sqlite_path=str(Path(temp_dir) / "runs.sqlite3"),
                    workspace_root=str(Path(temp_dir) / "workspace"),
                    branch_prefix="clawharness",
                    lock_ttl_seconds=60,
                    dedupe_ttl_seconds=60,
                ),
                openclaw_hooks=OpenClawHooksConfig(
                    base_url="http://127.0.0.1:18789",
                    token="token",
                    path="/hooks",
                    agent_id="agent",
                    default_session_key="default",
                    wake_mode="wake",
                ),
                openclaw_gateway_token=None,
                ingress_token=None,
                owner="owner",
                github=None,
                local_task=LocalTaskRuntimeConfig(
                    mode="local-task",
                    repository_path=temp_dir,
                    task_directory=temp_dir,
                    review_directory=temp_dir,
                    base_branch="main",
                    push_enabled=False,
                ),
                default_task_provider="local-task",
            )
            manifest = {
                "id": "test-plugin",
                "version": "1.0.0",
                "capabilities": [
                    {
                        "type": "task-provider",
                        "id": "ado",
                        "factory": "harness_runtime.provider_factories:create_azure_devops_task_provider",
                    },
                    {
                        "type": "task-provider",
                        "id": "github",
                        "factory": "harness_runtime.provider_factories:create_github_task_provider",
                    },
                    {
                        "type": "task-provider",
                        "id": "local",
                        "factory": "harness_runtime.provider_factories:create_local_task_provider",
                    },
                ],
            }

            providers = CapabilityRegistry.from_payload(manifest).instantiate_task_providers(config)

            self.assertNotIn("ado", providers)
            self.assertNotIn("github", providers)
            self.assertIsInstance(providers["local"], LocalTaskClient)

    def test_instantiate_capabilities_builds_executor_and_notifier_types(self) -> None:
        class RecordingGatewayToolClient:
            def invoke_tool(self, *, tool: str, args: dict[str, object], action: str | None = None):
                return {"tool": tool, "args": dict(args), "action": action}

        with tempfile.TemporaryDirectory() as temp_dir:
            config = HarnessRuntimeConfig(
                azure_devops=None,
                rocketchat=RocketChatRuntimeConfig(
                    mode="rocketchat-webhook",
                    webhook_url="https://chat.example/hooks/1/abc",
                    channel="#ai-dev",
                ),
                executor=ExecutorRuntimeConfig(mode="codex-cli", harness="codex", backend="codex-cli", timeout_seconds=60),
                runtime=RuntimeStorageConfig(
                    sqlite_path=str(Path(temp_dir) / "runs.sqlite3"),
                    workspace_root=str(Path(temp_dir) / "workspace"),
                    branch_prefix="clawharness",
                    lock_ttl_seconds=60,
                    dedupe_ttl_seconds=60,
                ),
                openclaw_hooks=OpenClawHooksConfig(
                    base_url="http://127.0.0.1:18789",
                    token="token",
                    path="/hooks",
                    agent_id="agent",
                    default_session_key="default",
                    wake_mode="wake",
                ),
                openclaw_gateway_token="gateway-token",
                ingress_token=None,
                owner="owner",
                github=None,
                local_task=None,
                shell_enabled=True,
            )

            registry = load_default_capability_registry()
            context = RuntimeCapabilityContext(
                config=config,
                gateway_tool_client=RecordingGatewayToolClient(),
            )

            executors = registry.instantiate_capabilities("executor", context)
            notifiers = registry.instantiate_capabilities("notifier", context)

            self.assertIsInstance(executors["codex-cli"], CodexCliRunner)
            self.assertIsInstance(executors["codex-acp"], CodexAcpRunner)
            self.assertIsInstance(notifiers["rocketchat-webhook"], RocketChatNotifier)

    def test_invalid_factory_path_is_rejected(self) -> None:
        registry = CapabilityRegistry.from_payload(
            {
                "id": "bad-plugin",
                "version": "1.0.0",
                "capabilities": [
                    {
                        "type": "task-provider",
                        "id": "broken",
                        "factory": "not-a-valid-factory",
                    }
                ],
            }
        )

        with self.assertRaises(CapabilityRegistryError):
            registry.instantiate_task_providers(
                HarnessRuntimeConfig(
                    azure_devops=None,
                    rocketchat=RocketChatRuntimeConfig(mode="disabled", webhook_url=None, channel=None),
                    executor=ExecutorRuntimeConfig(
                        mode="acp",
                        harness="openclaw",
                        backend="gateway",
                        timeout_seconds=60,
                    ),
                    runtime=RuntimeStorageConfig(
                        sqlite_path="runs.sqlite3",
                        workspace_root="workspace",
                        branch_prefix="clawharness",
                        lock_ttl_seconds=60,
                        dedupe_ttl_seconds=60,
                    ),
                    openclaw_hooks=OpenClawHooksConfig(
                        base_url="http://127.0.0.1:18789",
                        token="token",
                        path="/hooks",
                        agent_id="agent",
                        default_session_key="default",
                        wake_mode="wake",
                    ),
                    openclaw_gateway_token=None,
                    ingress_token=None,
                    owner="owner",
                    github=None,
                    local_task=None,
                )
            )


if __name__ == "__main__":
    unittest.main()
