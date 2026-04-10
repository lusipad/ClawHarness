from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"Invalid boolean environment value for {name}: {raw}")


def _string_env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    stripped = value.strip()
    if not stripped:
        return default
    return stripped


def _normalize_executor_backend(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    aliases = {
        "": "codex-cli",
        "cli": "codex-cli",
        "codex-cli": "codex-cli",
        "acp": "codex-acp",
        "acpx": "codex-acp",
        "gateway": "codex-acp",
        "codex-acp": "codex-acp",
    }
    return aliases.get(normalized, normalized or "codex-cli")


def _yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def build_providers_yaml() -> str:
    profile = _string_env("HARNESS_PROVIDER_PROFILE", "local-task").lower()
    if profile not in {"local-task", "azure-devops", "github"}:
        raise ValueError(f"Unsupported HARNESS_PROVIDER_PROFILE: {profile}")

    chat_mode = "rocketchat-webhook" if os.environ.get("RC_WEBHOOK_URL", "").strip() else "disabled"
    executor_backend = _normalize_executor_backend(_string_env("HARNESS_EXECUTOR_BACKEND", "codex-cli"))
    executor_mode = "codex-cli" if executor_backend == "codex-cli" else "codex-acp"
    executor_family = "codex" if executor_mode == "codex-cli" else "acp"

    lines = [
        "providers:",
        "  task_pr_ci:",
        f"    default_provider: {_yaml_scalar(profile)}",
    ]

    if profile == "local-task":
        lines.extend(
            [
                "    local_task:",
                "      family: local-task",
                "      mode: local-file",
                f"      repository_path: {_yaml_scalar(_string_env('LOCAL_REPO_PATH', '/mnt/local-repo'))}",
                f"      task_directory: {_yaml_scalar(_string_env('LOCAL_TASKS_PATH', '/mnt/local-tasks'))}",
                f"      review_directory: {_yaml_scalar(_string_env('LOCAL_REVIEW_PATH', '/mnt/local-reviews'))}",
                f"      base_branch: {_yaml_scalar(os.environ.get('LOCAL_BASE_BRANCH') or None)}",
                f"      push_enabled: {_yaml_scalar(_bool_env('LOCAL_PUSH_ENABLED', False))}",
            ]
        )
    elif profile == "azure-devops":
        lines.extend(
            [
                "    azure_devops:",
                "      family: azure-devops",
                "      mode: ado-rest",
                f"      base_url: {_yaml_scalar(_string_env('ADO_BASE_URL', 'https://dev.azure.com/example-org'))}",
                f"      project: {_yaml_scalar(_string_env('ADO_PROJECT', 'ExampleProject'))}",
                "      auth:",
                "        type: pat",
                "        secret_env: ADO_PAT",
                "      events:",
                "        mode: webhook",
                "        webhook_secret_env: ADO_WEBHOOK_SECRET",
            ]
        )
    else:
        lines.extend(
            [
                "    github:",
                "      family: github",
                "      mode: github-rest",
                f"      base_url: {_yaml_scalar(_string_env('GITHUB_BASE_URL', 'https://api.github.com'))}",
                "      auth:",
                "        type: token",
                "        secret_env: GITHUB_TOKEN",
                "      events:",
                "        mode: webhook",
                "        webhook_secret_env: GITHUB_WEBHOOK_SECRET",
            ]
        )

    lines.extend(
        [
            "  chat:",
            "    family: rocketchat",
            f"    mode: {_yaml_scalar(chat_mode)}",
            f"    room: {_yaml_scalar(_string_env('RC_ROOM', 'ai-dev'))}",
            "    webhook_url_env: RC_WEBHOOK_URL",
            "    command_token_env: RC_COMMAND_TOKEN",
            "  executor:",
            f"    family: {_yaml_scalar(executor_family)}",
            f"    mode: {_yaml_scalar(executor_mode)}",
            "    harness: codex",
            f"    backend: {_yaml_scalar(executor_backend)}",
            "    runtime:",
            f"      timeout_seconds: {_yaml_scalar(int(_string_env('HARNESS_EXECUTOR_TIMEOUT_SECONDS', '3600')))}",
            "runtime:",
            "  shell:",
            f"    enabled: {_yaml_scalar(_bool_env('HARNESS_SHELL_ENABLED', False))}",
            "  storage:",
            "    kind: sqlite",
            f"    path: {_yaml_scalar(_string_env('HARNESS_SQLITE_PATH', '~/.openclaw/harness/harness.db'))}",
            f"  workspace_root: {_yaml_scalar(_string_env('HARNESS_WORKSPACE_ROOT', '~/.openclaw/workspace/harness'))}",
            f"  branch_prefix: {_yaml_scalar(_string_env('HARNESS_BRANCH_PREFIX', 'ai'))}",
            f"  owner: {_yaml_scalar(_string_env('HARNESS_OWNER', 'harness-bridge'))}",
            f"  lock_ttl_seconds: {_yaml_scalar(int(_string_env('HARNESS_LOCK_TTL_SECONDS', '1800')))}",
            f"  dedupe_ttl_seconds: {_yaml_scalar(int(_string_env('HARNESS_DEDUPE_TTL_SECONDS', '86400')))}",
            f"  audit_retention_days: {_yaml_scalar(int(_string_env('HARNESS_AUDIT_RETENTION_DAYS', '30')))}",
            f"  terminal_run_retention_days: {_yaml_scalar(int(_string_env('HARNESS_TERMINAL_RUN_RETENTION_DAYS', '30')))}",
            f"  cleanup_batch_size: {_yaml_scalar(int(_string_env('HARNESS_CLEANUP_BATCH_SIZE', '50')))}",
        ]
    )
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render ClawHarness provider config from environment")
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_providers_yaml(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
