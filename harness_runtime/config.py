from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .simple_yaml import SimpleYamlError, load_simple_yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AzureDevOpsRuntimeConfig:
    base_url: str
    project: str
    mode: str
    pat: str | None
    webhook_secret: str | None


@dataclass(frozen=True)
class GitHubRuntimeConfig:
    base_url: str
    mode: str
    token: str | None
    webhook_secret: str | None


@dataclass(frozen=True)
class LocalTaskRuntimeConfig:
    mode: str
    repository_path: str | None
    task_directory: str | None
    review_directory: str | None
    base_branch: str | None
    push_enabled: bool


@dataclass(frozen=True)
class RocketChatRuntimeConfig:
    mode: str
    webhook_url: str | None
    channel: str | None
    command_token: str | None = None


@dataclass(frozen=True)
class ExecutorRuntimeConfig:
    mode: str
    harness: str
    backend: str
    timeout_seconds: int


@dataclass(frozen=True)
class RuntimeStorageConfig:
    sqlite_path: str
    workspace_root: str
    branch_prefix: str
    lock_ttl_seconds: int
    dedupe_ttl_seconds: int
    audit_retention_days: int = 30
    terminal_run_retention_days: int = 30
    cleanup_batch_size: int = 50


@dataclass(frozen=True)
class OpenClawHooksConfig:
    base_url: str
    token: str
    path: str
    agent_id: str
    default_session_key: str
    wake_mode: str


@dataclass(frozen=True)
class HarnessRuntimeConfig:
    azure_devops: AzureDevOpsRuntimeConfig | None
    rocketchat: RocketChatRuntimeConfig
    executor: ExecutorRuntimeConfig
    runtime: RuntimeStorageConfig
    openclaw_hooks: OpenClawHooksConfig | None
    openclaw_gateway_token: str | None
    ingress_token: str | None
    owner: str
    github: GitHubRuntimeConfig | None = None
    local_task: LocalTaskRuntimeConfig | None = None
    default_task_provider: str = "azure-devops"
    readonly_token: str | None = None
    control_token: str | None = None
    shell_enabled: bool = False


def load_harness_runtime_config(
    *,
    providers_path: str | Path,
    policy_path: str | Path,
    openclaw_path: str | Path,
    env: Mapping[str, str] | None = None,
) -> HarnessRuntimeConfig:
    env_map = dict(os.environ if env is None else env)
    providers = _load_yaml_file(providers_path)
    _ = _load_yaml_file(policy_path)

    providers_root = _require_mapping(providers, "providers")
    runtime_root = _require_mapping(providers, "runtime")

    task_pr_ci = _require_mapping(providers_root, "task_pr_ci")
    chat = _require_mapping(providers_root, "chat")
    executor = _require_mapping(providers_root, "executor")
    storage = _require_mapping(runtime_root, "storage")
    shell_root = _optional_mapping(runtime_root, "shell")
    shell_enabled = _resolve_shell_enabled(
        shell_root=shell_root,
        env_map=env_map,
        openclaw_path=openclaw_path,
    )

    azure_devops_root = _resolve_provider_mapping(task_pr_ci, family="azure-devops", nested_key="azure_devops")
    github_root = _resolve_provider_mapping(task_pr_ci, family="github", nested_key="github")
    local_task_root = _resolve_provider_mapping(task_pr_ci, family="local-task", nested_key="local_task")
    default_task_provider = _optional_string(task_pr_ci, "default_provider") or _optional_string(task_pr_ci, "family")
    if not default_task_provider:
        if local_task_root is not None:
            default_task_provider = "local-task"
        elif azure_devops_root is not None:
            default_task_provider = "azure-devops"
        elif github_root is not None:
            default_task_provider = "github"
        else:
            default_task_provider = "local-task"

    openclaw_hooks = None
    openclaw_gateway_token = None
    owner = _resolve_runtime_owner(runtime_root, env_map)
    ingress_token = env_map.get("HARNESS_INGRESS_TOKEN")
    if shell_enabled:
        openclaw = _load_json_file(openclaw_path)
        hooks = _require_mapping(openclaw, "hooks")
        openclaw_hooks = OpenClawHooksConfig(
            base_url=_require_resolved_string(openclaw, "gatewayBaseUrl", env_map),
            token=_resolve_placeholder(_require_string(hooks, "token"), env_map),
            path=_require_resolved_string(hooks, "path", env_map),
            agent_id=_require_resolved_string(hooks, "defaultAgentId", env_map),
            default_session_key=_require_resolved_string(hooks, "defaultSessionKey", env_map),
            wake_mode=_require_resolved_string(hooks, "wakeMode", env_map),
        )
        openclaw_gateway_token = _resolve_placeholder(_optional_string(openclaw, "gatewayToken"), env_map)
        owner = _resolve_runtime_owner(runtime_root, env_map, fallback=_resolve_runtime_owner(hooks, env_map))
        ingress_token = _resolve_placeholder(_optional_string(hooks, "ingressToken"), env_map) or ingress_token

    return HarnessRuntimeConfig(
        azure_devops=_load_azure_devops_runtime_config(azure_devops_root, env_map),
        rocketchat=RocketChatRuntimeConfig(
            mode=_require_resolved_string(chat, "mode", env_map),
            webhook_url=_resolve_secret(chat, env_map, "webhook_url_env"),
            channel=_optional_string(chat, "room"),
            command_token=_resolve_secret(chat, env_map, "command_token_env"),
        ),
        executor=ExecutorRuntimeConfig(
            mode=_require_resolved_string(executor, "mode", env_map),
            harness=_require_resolved_string(executor, "harness", env_map),
            backend=_require_resolved_string(executor, "backend", env_map),
            timeout_seconds=int(_require_mapping(executor, "runtime").get("timeout_seconds", 3600)),
        ),
        runtime=RuntimeStorageConfig(
            sqlite_path=_expand_filesystem_path(_require_string(storage, "path"), env_map),
            workspace_root=_expand_filesystem_path(_require_string(runtime_root, "workspace_root"), env_map),
            branch_prefix=_require_resolved_string(runtime_root, "branch_prefix", env_map),
            lock_ttl_seconds=int(runtime_root.get("lock_ttl_seconds", 1800)),
            dedupe_ttl_seconds=int(runtime_root.get("dedupe_ttl_seconds", 86400)),
            audit_retention_days=int(runtime_root.get("audit_retention_days", 30)),
            terminal_run_retention_days=int(runtime_root.get("terminal_run_retention_days", 30)),
            cleanup_batch_size=int(runtime_root.get("cleanup_batch_size", 50)),
        ),
        openclaw_hooks=openclaw_hooks,
        openclaw_gateway_token=openclaw_gateway_token,
        ingress_token=ingress_token,
        github=_load_github_runtime_config(github_root, env_map),
        local_task=_load_local_task_runtime_config(local_task_root, env_map),
        default_task_provider=default_task_provider,
        readonly_token=env_map.get("HARNESS_READONLY_TOKEN"),
        control_token=env_map.get("HARNESS_CONTROL_TOKEN"),
        owner=owner,
        shell_enabled=shell_enabled,
    )


def _load_yaml_file(path: str | Path) -> dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Failed to read YAML file: {path}") from exc
    try:
        return load_simple_yaml(text)
    except SimpleYamlError as exc:
        raise ConfigError(f"Failed to parse YAML file {path}: {exc}") from exc


def _load_json_file(path: str | Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Failed to read JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Failed to parse JSON file {path}: {exc}") from exc


def _require_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ConfigError(f"Missing mapping: {key}")
    return value


def _optional_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ConfigError(f"Expected mapping: {key}")
    return value


def _resolve_provider_mapping(
    mapping: Mapping[str, Any],
    *,
    family: str,
    nested_key: str,
) -> Mapping[str, Any] | None:
    nested = mapping.get(nested_key)
    if isinstance(nested, Mapping):
        return nested
    candidate_family = mapping.get("family")
    if candidate_family == family:
        return mapping
    return None


def _resolve_shell_enabled(
    *,
    shell_root: Mapping[str, Any] | None,
    env_map: Mapping[str, str],
    openclaw_path: str | Path,
) -> bool:
    env_value = env_map.get("HARNESS_SHELL_ENABLED")
    if env_value is not None:
        return _parse_bool(env_value, key="HARNESS_SHELL_ENABLED")
    if shell_root is not None and "enabled" in shell_root:
        return _resolve_optional_bool(shell_root, env_map, "enabled", default=False)
    return Path(openclaw_path).exists()


def _resolve_runtime_owner(
    mapping: Mapping[str, Any],
    env_map: Mapping[str, str],
    *,
    fallback: str | None = None,
) -> str:
    resolved = _resolve_optional_string(mapping, env_map, "owner")
    if resolved:
        return resolved
    if fallback:
        return fallback
    return env_map.get("HARNESS_OWNER", "").strip() or "harness-bridge"


def _load_azure_devops_runtime_config(
    mapping: Mapping[str, Any] | None,
    env_map: Mapping[str, str],
) -> AzureDevOpsRuntimeConfig | None:
    if mapping is None:
        return None
    return AzureDevOpsRuntimeConfig(
        base_url=_require_resolved_string(mapping, "base_url", env_map),
        project=_require_resolved_string(mapping, "project", env_map),
        mode=_require_resolved_string(mapping, "mode", env_map),
        pat=_resolve_secret(_require_mapping(mapping, "auth"), env_map, "secret_env"),
        webhook_secret=_resolve_nested_secret(mapping, env_map, "events", "webhook_secret_env"),
    )


def _load_github_runtime_config(
    mapping: Mapping[str, Any] | None,
    env_map: Mapping[str, str],
) -> GitHubRuntimeConfig | None:
    if mapping is None:
        return None
    return GitHubRuntimeConfig(
        base_url=_resolve_required_string(
            _optional_string(mapping, "base_url") or "https://api.github.com",
            "github.base_url",
            env_map,
        ),
        mode=_require_resolved_string(mapping, "mode", env_map),
        token=_resolve_secret(_require_mapping(mapping, "auth"), env_map, "secret_env"),
        webhook_secret=_resolve_nested_secret(mapping, env_map, "events", "webhook_secret_env"),
    )


def _load_local_task_runtime_config(
    mapping: Mapping[str, Any] | None,
    env_map: Mapping[str, str],
) -> LocalTaskRuntimeConfig | None:
    if mapping is None:
        return None
    return LocalTaskRuntimeConfig(
        mode=_require_resolved_string(mapping, "mode", env_map),
        repository_path=_resolve_optional_path(mapping, env_map, "repository_path"),
        task_directory=_resolve_optional_path(mapping, env_map, "task_directory"),
        review_directory=_resolve_optional_path(mapping, env_map, "review_directory"),
        base_branch=_resolve_optional_string(mapping, env_map, "base_branch"),
        push_enabled=_resolve_optional_bool(mapping, env_map, "push_enabled", default=False),
    )


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"Missing string: {key}")
    return value


def _require_resolved_string(mapping: Mapping[str, Any], key: str, env_map: Mapping[str, str]) -> str:
    return _resolve_required_string(_require_string(mapping, key), key, env_map)


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"Expected string: {key}")
    return value


def _resolve_secret(mapping: Mapping[str, Any], env_map: Mapping[str, str], env_key_field: str) -> str | None:
    env_name = mapping.get(env_key_field)
    if env_name is None:
        return None
    if not isinstance(env_name, str) or not env_name:
        raise ConfigError(f"Invalid env reference field: {env_key_field}")
    return env_map.get(env_name)


def _resolve_nested_secret(
    mapping: Mapping[str, Any],
    env_map: Mapping[str, str],
    nested_key: str,
    env_key_field: str,
) -> str | None:
    nested = mapping.get(nested_key)
    if not isinstance(nested, Mapping):
        return None
    return _resolve_secret(nested, env_map, env_key_field)


def _resolve_placeholder(value: str | None, env_map: Mapping[str, str]) -> str | None:
    if value is None:
        return None
    if value.startswith("${") and value.endswith("}"):
        return env_map.get(value[2:-1])
    return value


def _resolve_required_string(value: str, key: str, env_map: Mapping[str, str]) -> str:
    resolved = _resolve_placeholder(value, env_map)
    if not resolved:
        raise ConfigError(f"Missing resolved string: {key}")
    return resolved


def _resolve_optional_string(mapping: Mapping[str, Any], env_map: Mapping[str, str], key: str) -> str | None:
    value = _optional_string(mapping, key)
    if value is None:
        return None
    resolved = _resolve_placeholder(value, env_map)
    return resolved or None


def _resolve_optional_path(mapping: Mapping[str, Any], env_map: Mapping[str, str], key: str) -> str | None:
    resolved = _resolve_optional_string(mapping, env_map, key)
    if resolved is None:
        return None
    return _expand_filesystem_path(resolved, env_map)


def _resolve_optional_bool(
    mapping: Mapping[str, Any],
    env_map: Mapping[str, str],
    key: str,
    *,
    default: bool,
) -> bool:
    value = mapping.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _parse_bool((_resolve_placeholder(value, env_map) or value).strip(), key=key)
    raise ConfigError(f"Expected boolean: {key}")


def _parse_bool(value: str, *, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ConfigError(f"Expected boolean: {key}")


_PATH_VAR_PATTERN = re.compile(r"%([^%]+)%|\$\{([^}]+)\}")


def _expand_filesystem_path(value: str, env_map: Mapping[str, str]) -> str:
    expanded = _PATH_VAR_PATTERN.sub(
        lambda match: env_map.get(match.group(1) or match.group(2), match.group(0)),
        value,
    )
    if expanded == "~":
        expanded = _resolve_home_directory(env_map)
    elif expanded.startswith("~/") or expanded.startswith("~\\"):
        expanded = str(Path(_resolve_home_directory(env_map)) / expanded[2:])
    return str(Path(expanded))


def _resolve_home_directory(env_map: Mapping[str, str]) -> str:
    home = env_map.get("USERPROFILE") or env_map.get("HOME")
    if home:
        return home
    return str(Path("~").expanduser())
