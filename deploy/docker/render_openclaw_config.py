from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping


PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def render_template(template_text: str, env: dict[str, str]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = env.get(name)
        if not value:
            missing.add(name)
            return match.group(0)
        return value

    rendered = PLACEHOLDER_PATTERN.sub(replace, template_text)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing required environment variables for OpenClaw config: {missing_list}")
    return rendered


def build_bridge_runtime_config(gateway_config: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    gateway_root = _require_mapping(gateway_config, "gateway")
    auth_root = _require_mapping(gateway_root, "auth")
    hooks_root = _require_mapping(gateway_config, "hooks")

    output: dict[str, Any] = {
        "gatewayBaseUrl": env.get("OPENCLAW_GATEWAY_BASE_URL", "http://openclaw-gateway:18789"),
        "gatewayToken": _require_string(auth_root, "token"),
        "hooks": {
            "enabled": bool(hooks_root.get("enabled", True)),
            "token": _require_string(hooks_root, "token"),
            "path": _string_or_default(hooks_root.get("path"), "/hooks"),
            "defaultAgentId": env.get("OPENCLAW_HOOKS_DEFAULT_AGENT_ID", "hooks"),
            "defaultSessionKey": _string_or_default(hooks_root.get("defaultSessionKey"), "hook:harness"),
            "wakeMode": env.get("OPENCLAW_HOOKS_WAKE_MODE", "now"),
            "owner": env.get("HARNESS_OWNER", "harness-bridge"),
        },
    }
    ingress_token = env.get("HARNESS_INGRESS_TOKEN")
    if ingress_token:
        output["hooks"]["ingressToken"] = ingress_token
    return output


def _require_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"Missing mapping in gateway config: {key}")
    return value


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing string in gateway config: {key}")
    return value


def _string_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render the Docker OpenClaw config template")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--template")
    source_group.add_argument("--gateway-config")
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.template:
        template_path = Path(args.template)
        template_text = template_path.read_text(encoding="utf-8")
        rendered = render_template(template_text, dict(os.environ))
        output_path.write_text(rendered, encoding="utf-8")
        return 0

    gateway_config_path = Path(args.gateway_config)
    gateway_config = json.loads(gateway_config_path.read_text(encoding="utf-8"))
    rendered_payload = build_bridge_runtime_config(gateway_config, dict(os.environ))
    output_path.write_text(json.dumps(rendered_payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
