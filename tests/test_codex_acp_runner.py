from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_acp_runner import CodexAcpRunner, ExecutorRequest, ExecutorRunError


class RecordingSpawner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, payload: dict) -> dict:
        self.calls.append(payload)
        return {
            "accepted": True,
            "childSessionKey": "agent:codex:acp:123",
            "sessionId": "session-123",
            "streamLogPath": "/tmp/stream.jsonl",
        }


class CodexAcpRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spawner = RecordingSpawner()
        self.runner = CodexAcpRunner(self.spawner)

    def make_request(self, **overrides) -> ExecutorRequest:
        payload = {
            "workspace_path": "D:/Repos/claw_az",
            "task_prompt": "Implement task AB#123",
            "constraints": ["use existing patterns", "run tests before finishing"],
            "artifacts": {"task": {"id": "123"}},
            "label": "task-123",
            "mode": "run",
            "thread": False,
            "agent_id": "codex",
            "stream_to_parent": True,
        }
        payload.update(overrides)
        return ExecutorRequest(**payload)

    def test_build_task_prompt_renders_constraints_and_artifacts(self) -> None:
        prompt = self.runner.build_task_prompt(self.make_request())

        self.assertIn("Implement task AB#123", prompt)
        self.assertIn("- use existing patterns", prompt)
        self.assertIn('"id": "123"', prompt)

    def test_build_task_prompt_includes_result_contract_when_present(self) -> None:
        request = self.make_request(artifacts={"task": {"id": "123"}, "result_path": "D:/tmp/result.json"})

        prompt = self.runner.build_task_prompt(request)

        self.assertIn("Execution contract:", prompt)
        self.assertIn("D:/tmp/result.json", prompt)
        self.assertIn('"checks"', prompt)

    def test_build_spawn_payload_uses_acp_runtime(self) -> None:
        payload = self.runner.build_spawn_payload(self.make_request())

        self.assertEqual("acp", payload["runtime"])
        self.assertEqual("codex", payload["agentId"])
        self.assertEqual("run", payload["mode"])
        self.assertEqual("D:/Repos/claw_az", payload["cwd"])
        self.assertEqual("parent", payload["streamTo"])
        self.assertNotIn("resumeSessionId", payload)

    def test_session_mode_requires_thread_binding(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.build_spawn_payload(self.make_request(mode="session", thread=False))

    def test_resume_includes_resume_session_id(self) -> None:
        self.runner.resume(self.make_request(mode="session", thread=True), resume_session_id="resume-1")

        payload = self.spawner.calls[0]
        self.assertEqual("resume-1", payload["resumeSessionId"])
        self.assertTrue(payload["thread"])

    def test_start_parses_spawn_response(self) -> None:
        result = self.runner.start(self.make_request())

        self.assertTrue(result.accepted)
        self.assertEqual("agent:codex:acp:123", result.child_session_key)
        self.assertEqual("session-123", result.session_id)
        self.assertEqual("/tmp/stream.jsonl", result.stream_log_path)

    def test_start_parses_openclaw_tool_wrapped_spawn_response(self) -> None:
        self.spawner = lambda payload: {
            "content": [{"type": "text", "text": "accepted"}],
            "details": {
                "status": "accepted",
                "childSessionKey": "agent:codex:acp:wrapped",
                "runId": "run-123",
            },
        }
        self.runner = CodexAcpRunner(self.spawner)

        result = self.runner.start(self.make_request())

        self.assertTrue(result.accepted)
        self.assertEqual("agent:codex:acp:wrapped", result.child_session_key)
        self.assertEqual("agent:codex:acp:wrapped", result.session_id)

    def test_wait_for_result_loads_structured_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "executor-result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "Applied patch",
                        "changed_files": ["README.md"],
                        "checks": [{"name": "git diff --check", "status": "passed"}],
                        "follow_up": [],
                    }
                ),
                encoding="utf-8",
            )

            result = self.runner.wait_for_result(result_path, timeout_seconds=0.1, poll_interval_seconds=0.01)

        self.assertEqual("completed", result.status)
        self.assertEqual(["README.md"], result.changed_files)

    def test_run_and_wait_uses_inline_result_when_returned(self) -> None:
        self.spawner = lambda payload: {
            "accepted": True,
            "sessionId": "session-inline",
            "result": {
                "status": "completed",
                "summary": "Inline result",
                "changed_files": ["README.md"],
                "checks": [],
                "follow_up": ["open pr"],
            },
        }
        self.runner = CodexAcpRunner(self.spawner)

        outcome = self.runner.run_and_wait(
            self.make_request(),
            result_path="D:/tmp/result.json",
            timeout_seconds=0.1,
            poll_interval_seconds=0.01,
        )

        self.assertEqual("session-inline", outcome.spawn.session_id)
        self.assertEqual("Inline result", outcome.result.summary)

    def test_run_and_wait_normalizes_inline_string_checks(self) -> None:
        self.spawner = lambda payload: {
            "accepted": True,
            "sessionId": "session-inline",
            "result": {
                "status": "completed",
                "summary": "Inline result",
                "changed_files": ["README.md"],
                "checks": ["confirm README", "append section"],
                "follow_up": [],
            },
        }
        self.runner = CodexAcpRunner(self.spawner)

        outcome = self.runner.run_and_wait(
            self.make_request(),
            result_path="D:/tmp/result.json",
            timeout_seconds=0.1,
            poll_interval_seconds=0.01,
        )

        self.assertEqual("confirm README", outcome.result.checks[0]["name"])
        self.assertEqual("informational", outcome.result.checks[0]["status"])

    def test_run_and_wait_raises_when_result_times_out(self) -> None:
        with self.assertRaises(ExecutorRunError):
            self.runner.run_and_wait(
                self.make_request(),
                result_path="D:/tmp/non-existent-result.json",
                timeout_seconds=0.01,
                poll_interval_seconds=0.001,
            )

    def test_workspace_must_be_absolute(self) -> None:
        with self.assertRaises(ValueError):
            self.runner.build_spawn_payload(self.make_request(workspace_path="relative/path"))


if __name__ == "__main__":
    unittest.main()
