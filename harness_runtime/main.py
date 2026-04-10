from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from run_store import RunStore
from workflow_provider import WorkflowProviderClient

from .bridge import HarnessBridge
from .capability_registry import RuntimeCapabilityContext, load_default_capability_registry
from .config import HarnessRuntimeConfig, load_harness_runtime_config
from .image_analyzer import OpenAIImageAnalyzer
from .maintenance import RunMaintenanceService
from .openclaw_client import OpenClawWebhookClient
from .orchestrator import TaskRunOrchestrator
from .server import serve


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ClawHarness bridge service")
    parser.add_argument("--providers-config", default="deploy/config/providers.yaml")
    parser.add_argument("--policy-config", default="deploy/config/harness-policy.yaml")
    parser.add_argument("--openclaw-config", default="deploy/config/openclaw.json")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--task-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--provider-type")
    parser.add_argument("--source-id")
    parser.add_argument("--run-maintenance", action="store_true")
    parser.add_argument("--cleanup-retention-days", type=int)
    parser.add_argument("--cleanup-limit", type=int)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    config = load_harness_runtime_config(
        providers_path=Path(args.providers_config),
        policy_path=Path(args.policy_config),
        openclaw_path=Path(args.openclaw_config),
    )
    store = RunStore(config.runtime.sqlite_path)
    store.initialize()

    if args.run_maintenance:
        maintenance = RunMaintenanceService(config=config, store=store)
        result = maintenance.cleanup_terminal_runs(
            retention_days=args.cleanup_retention_days,
            limit=args.cleanup_limit,
        )
        print(json.dumps(result.to_payload(), ensure_ascii=False))
        return 0

    openclaw_client = None
    gateway_tool_client = None
    if config.openclaw_hooks is not None:
        openclaw_client = OpenClawWebhookClient(
            base_url=config.openclaw_hooks.base_url,
            token=config.openclaw_hooks.token,
            path=config.openclaw_hooks.path,
        )
        gateway_tool_client = OpenClawWebhookClient(
            base_url=config.openclaw_hooks.base_url,
            token=config.openclaw_gateway_token or config.openclaw_hooks.token,
            path=config.openclaw_hooks.path,
        )

    capability_registry = load_default_capability_registry()
    capability_context = RuntimeCapabilityContext(
        config=config,
        openclaw_client=openclaw_client,
        gateway_tool_client=gateway_tool_client,
    )
    provider_instances = capability_registry.instantiate_capabilities("task-provider", capability_context)
    provider_clients: dict[str, WorkflowProviderClient] = {
        key: value
        for key, value in provider_instances.items()
        if isinstance(value, WorkflowProviderClient)
    }
    ado_client = provider_clients.get("azure-devops")
    github_client = provider_clients.get("github")
    notifier = _first_capability(
        capability_registry.instantiate_capabilities("notifier", capability_context),
        preferred_ids=("rocketchat-webhook",),
    )
    image_analyzer = None
    openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_api_key:
        image_model = (
            os.environ.get("HARNESS_IMAGE_MODEL", "").strip()
            or os.environ.get("CODEX_REVIEW_MODEL", "").strip()
            or os.environ.get("CODEX_MODEL", "").strip()
            or "gpt-4.1-mini"
        )
        image_analyzer = OpenAIImageAnalyzer(
            api_key=openai_api_key,
            base_url=os.environ.get("OPENAI_BASE_URL", "").strip() or None,
            model=image_model,
        )

    executor_instances = capability_registry.instantiate_capabilities("executor", capability_context)
    executor_id = _resolve_executor_capability_id(config)
    executor_runner = _pick_required_capability(executor_instances, executor_id)

    if args.task_id:
        effective_provider_type = args.provider_type or config.default_task_provider
        effective_repo_id = args.repo_id
        if not effective_repo_id and effective_provider_type == "local-task" and config.local_task is not None:
            effective_repo_id = config.local_task.repository_path
        if not effective_repo_id:
            parser.error("--repo-id is required when --task-id is provided unless local-task.repository_path is configured")
        orchestrator = TaskRunOrchestrator(
            config=config,
            store=store,
            ado_client=ado_client,
            provider_clients=provider_clients,
            executor_runner=executor_runner,
            notifier=notifier,
        )
        run, task_context = orchestrator.claim_manual_task(
            task_id=str(args.task_id),
            repo_id=str(effective_repo_id),
            provider_type=effective_provider_type,
            source_id=args.source_id,
        )
        final_run = orchestrator.run_claimed_task(run.run_id, task_context=task_context)
        print(
            json.dumps(
                {
                    "run_id": final_run.run_id,
                    "status": final_run.status,
                    "branch_name": final_run.branch_name,
                    "pr_id": final_run.pr_id,
                    "workspace_path": final_run.workspace_path,
                    "last_error": final_run.last_error,
                },
                ensure_ascii=False,
            )
        )
        return 0 if final_run.status == "awaiting_review" else 1

    bridge = HarnessBridge(
        config=config,
        store=store,
        ado_client=ado_client,
        github_client=github_client,
        provider_clients=provider_clients,
        openclaw_client=openclaw_client,
        notifier=notifier,
        task_orchestrator=TaskRunOrchestrator(
            config=config,
            store=store,
            ado_client=ado_client,
            provider_clients=provider_clients,
            executor_runner=executor_runner,
            notifier=notifier,
        ),
        image_analyzer=image_analyzer,
    )
    serve(
        bridge,
        host=args.bind,
        port=args.port,
        ingress_token=config.ingress_token,
        readonly_token=config.readonly_token,
        control_token=config.control_token,
        chat_command_token=config.rocketchat.command_token,
        github_webhook_secret=config.github.webhook_secret if config.github is not None else None,
    )
    return 0


def _resolve_executor_capability_id(config: HarnessRuntimeConfig) -> str:
    env_backend = _normalize_executor_capability_id(os.environ.get("HARNESS_EXECUTOR_BACKEND", ""))
    if env_backend:
        return env_backend

    normalized_backend = _normalize_executor_capability_id(config.executor.backend)
    if normalized_backend:
        return normalized_backend

    normalized_mode = _normalize_executor_capability_id(config.executor.mode)
    if normalized_mode:
        return normalized_mode
    return "codex-acp"


def _first_capability(instances: dict[str, object], *, preferred_ids: tuple[str, ...]) -> object | None:
    for capability_id in preferred_ids:
        if capability_id in instances:
            return instances[capability_id]
    return next(iter(instances.values()), None)


def _pick_required_capability(instances: dict[str, object], capability_id: str) -> object:
    selected = instances.get(capability_id)
    if selected is not None:
        return selected
    available = ", ".join(sorted(instances)) or "none"
    raise RuntimeError(f"Required capability is unavailable: {capability_id}; available: {available}")


def _normalize_executor_capability_id(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    aliases = {
        "": "",
        "cli": "codex-cli",
        "codex-cli": "codex-cli",
        "acp": "codex-acp",
        "acpx": "codex-acp",
        "gateway": "codex-acp",
        "codex-acp": "codex-acp",
    }
    return aliases.get(normalized, normalized)


if __name__ == "__main__":
    raise SystemExit(main())
