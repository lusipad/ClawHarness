from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "deploy" / "docker" / "render_openclaw_config.py"
PROVIDERS_RENDER_PATH = REPO_ROOT / "deploy" / "docker" / "render_providers_config.py"
NODE_PATH = shutil.which("node")
CODEX_AUTH_RENDER_PATH = REPO_ROOT / "deploy" / "docker" / "render_codex_auth.mjs"
CODEX_CONFIG_RENDER_PATH = REPO_ROOT / "deploy" / "docker" / "render_codex_config.mjs"


class DockerRenderConfigTests(unittest.TestCase):
    def test_render_openclaw_config_writes_rendered_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            template_path = base / "openclaw.json.template"
            output_path = base / "openclaw.json"
            template_path.write_text(
                """
{
  "gatewayBaseUrl": "${OPENCLAW_GATEWAY_BASE_URL}",
  "gatewayToken": "${OPENCLAW_GATEWAY_TOKEN}",
  "hooks": {
    "token": "${OPENCLAW_HOOKS_TOKEN}"
  },
  "agents": {
    "list": [
      {
        "runtime": {
          "acp": {
            "cwd": "${OPENCLAW_AGENT_CWD}"
          }
        }
      }
    ]
  }
}
""".strip(),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "OPENCLAW_GATEWAY_BASE_URL": "http://openclaw-gateway:18789",
                    "OPENCLAW_GATEWAY_TOKEN": "gateway-secret",
                    "OPENCLAW_HOOKS_TOKEN": "hooks-secret",
                    "OPENCLAW_AGENT_CWD": "/home/node/.openclaw/workspace/harness",
                }
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--template", str(template_path), "--output", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("http://openclaw-gateway:18789", payload["gatewayBaseUrl"])
            self.assertEqual("gateway-secret", payload["gatewayToken"])
            self.assertEqual("hooks-secret", payload["hooks"]["token"])
            self.assertEqual(
                "/home/node/.openclaw/workspace/harness",
                payload["agents"]["list"][0]["runtime"]["acp"]["cwd"],
            )

    def test_render_openclaw_config_fails_when_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            template_path = base / "openclaw.json.template"
            output_path = base / "openclaw.json"
            template_path.write_text('{"gatewayToken": "${OPENCLAW_GATEWAY_TOKEN}"}', encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--template", str(template_path), "--output", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env={},
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("OPENCLAW_GATEWAY_TOKEN", result.stderr)
            self.assertFalse(output_path.exists())

    def test_render_openclaw_config_from_gateway_json_writes_bridge_runtime_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            gateway_config_path = base / "gateway-openclaw.json"
            output_path = base / "bridge-openclaw.json"
            gateway_config_path.write_text(
                json.dumps(
                    {
                        "gateway": {
                            "auth": {
                                "mode": "token",
                                "token": "gateway-secret",
                            }
                        },
                        "hooks": {
                            "enabled": True,
                            "token": "hooks-secret",
                            "path": "/hooks-custom",
                            "defaultSessionKey": "hook:custom",
                        },
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "OPENCLAW_GATEWAY_BASE_URL": "http://openclaw-gateway:18789",
                    "HARNESS_INGRESS_TOKEN": "ingress-secret",
                }
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--gateway-config",
                    str(gateway_config_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("http://openclaw-gateway:18789", payload["gatewayBaseUrl"])
            self.assertEqual("gateway-secret", payload["gatewayToken"])
            self.assertEqual("hooks-secret", payload["hooks"]["token"])
            self.assertEqual("/hooks-custom", payload["hooks"]["path"])
            self.assertEqual("hook:custom", payload["hooks"]["defaultSessionKey"])
            self.assertEqual("hooks", payload["hooks"]["defaultAgentId"])
            self.assertEqual("now", payload["hooks"]["wakeMode"])
            self.assertEqual("harness-bridge", payload["hooks"]["owner"])
            self.assertEqual("ingress-secret", payload["hooks"]["ingressToken"])

    def test_render_providers_config_defaults_to_local_task_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_path = base / "providers.yaml"
            env = os.environ.copy()
            env.update(
                {
                    "LOCAL_REPO_PATH": "/mnt/local-repo",
                    "LOCAL_TASKS_PATH": "/mnt/local-tasks",
                    "LOCAL_REVIEW_PATH": "/mnt/local-reviews",
                }
            )

            result = subprocess.run(
                [sys.executable, str(PROVIDERS_RENDER_PATH), "--output", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            contents = output_path.read_text(encoding="utf-8")
            self.assertIn('default_provider: "local-task"', contents)
            self.assertIn("family: local-task", contents)
            self.assertIn("enabled: false", contents)
            self.assertIn('backend: "codex-cli"', contents)

    def test_render_providers_config_supports_azure_profile_and_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_path = base / "providers.yaml"
            env = os.environ.copy()
            env.update(
                {
                    "HARNESS_PROVIDER_PROFILE": "azure-devops",
                    "HARNESS_SHELL_ENABLED": "1",
                    "ADO_BASE_URL": "https://dev.azure.com/example-org",
                    "ADO_PROJECT": "ExampleProject",
                    "HARNESS_EXECUTOR_BACKEND": "codex-cli",
                }
            )

            result = subprocess.run(
                [sys.executable, str(PROVIDERS_RENDER_PATH), "--output", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            contents = output_path.read_text(encoding="utf-8")
            self.assertIn('default_provider: "azure-devops"', contents)
            self.assertIn("family: azure-devops", contents)
            self.assertIn("enabled: true", contents)

    def test_render_providers_config_maps_legacy_acpx_backend_to_codex_acp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            output_path = base / "providers.yaml"
            env = os.environ.copy()
            env.update(
                {
                    "HARNESS_PROVIDER_PROFILE": "local-task",
                    "HARNESS_EXECUTOR_BACKEND": "acpx",
                }
            )

            result = subprocess.run(
                [sys.executable, str(PROVIDERS_RENDER_PATH), "--output", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            contents = output_path.read_text(encoding="utf-8")
            self.assertIn('mode: "codex-acp"', contents)
            self.assertIn('backend: "codex-acp"', contents)

    @unittest.skipUnless(NODE_PATH, "node is required")
    def test_render_codex_auth_writes_auth_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "auth.json"
            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "sk-test-key"

            result = subprocess.run(
                [NODE_PATH, str(CODEX_AUTH_RENDER_PATH), str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("apikey", payload["auth_mode"])
            self.assertEqual("sk-test-key", payload["OPENAI_API_KEY"])

    @unittest.skipUnless(NODE_PATH, "node is required")
    def test_render_codex_auth_fails_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "auth.json"
            env = os.environ.copy()
            env.pop("OPENAI_API_KEY", None)

            result = subprocess.run(
                [NODE_PATH, str(CODEX_AUTH_RENDER_PATH), str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("OPENAI_API_KEY", result.stderr)
            self.assertFalse(output_path.exists())

    @unittest.skipUnless(NODE_PATH, "node is required")
    def test_render_codex_config_writes_config_toml_with_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "config.toml"
            env = os.environ.copy()
            env.update(
                {
                    "OPENAI_BASE_URL": "https://example.invalid/v1",
                    "CODEX_MODEL": "gpt-5.4",
                    "CODEX_REVIEW_MODEL": "gpt-5.4",
                    "CODEX_REASONING_EFFORT": "xhigh",
                }
            )

            result = subprocess.run(
                [NODE_PATH, str(CODEX_CONFIG_RENDER_PATH), str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            contents = output_path.read_text(encoding="utf-8")
            self.assertIn('model_provider = "openai"', contents)
            self.assertIn('model = "gpt-5.4"', contents)
            self.assertIn('review_model = "gpt-5.4"', contents)
            self.assertIn('model_reasoning_effort = "xhigh"', contents)
            self.assertIn('openai_base_url = "https://example.invalid/v1"', contents)

    @unittest.skipUnless(NODE_PATH, "node is required")
    def test_render_codex_config_omits_base_url_when_not_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "config.toml"
            env = os.environ.copy()
            env.pop("OPENAI_BASE_URL", None)
            env["CODEX_MODEL"] = "gpt-5.4"

            result = subprocess.run(
                [NODE_PATH, str(CODEX_CONFIG_RENDER_PATH), str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            contents = output_path.read_text(encoding="utf-8")
            self.assertIn('model_provider = "openai"', contents)
            self.assertIn('model = "gpt-5.4"', contents)
            self.assertNotIn("review_model", contents)
            self.assertNotIn("model_reasoning_effort", contents)
            self.assertNotIn("openai_base_url", contents)


if __name__ == "__main__":
    unittest.main()
