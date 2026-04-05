from __future__ import annotations

import argparse
import json
from pathlib import Path

from ado_client import AzureDevOpsRestClient
from codex_acp_runner import CodexAcpRunner
from rocketchat_notifier import RocketChatNotifier
from run_store import RunStore

from .bridge import HarnessBridge
from .config import load_harness_runtime_config
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
    parser.add_argument("--source-id")
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

    ado_client = AzureDevOpsRestClient(
        base_url=config.azure_devops.base_url,
        project=config.azure_devops.project,
        pat=config.azure_devops.pat,
    )
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
    notifier = None
    if config.rocketchat.webhook_url:
        notifier = RocketChatNotifier(
            webhook_url=config.rocketchat.webhook_url,
            default_channel=config.rocketchat.channel,
        )

    executor_runner = CodexAcpRunner(
        lambda payload: gateway_tool_client.invoke_tool(
            tool="sessions_spawn",
            action="session_spawn",
            args=payload,
        )
    )

    if args.task_id:
        if not args.repo_id:
            parser.error("--repo-id is required when --task-id is provided")
        orchestrator = TaskRunOrchestrator(
            config=config,
            store=store,
            ado_client=ado_client,
            executor_runner=executor_runner,
            notifier=notifier,
        )
        run, task_context = orchestrator.claim_manual_task(
            task_id=str(args.task_id),
            repo_id=str(args.repo_id),
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
        openclaw_client=openclaw_client,
        notifier=notifier,
        task_orchestrator=TaskRunOrchestrator(
            config=config,
            store=store,
            ado_client=ado_client,
            executor_runner=executor_runner,
            notifier=notifier,
        ),
    )
    serve(bridge, host=args.bind, port=args.port, ingress_token=config.ingress_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
