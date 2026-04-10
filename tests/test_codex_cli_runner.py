from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_acp_runner import CodexCliRunner, ExecutorRequest, ExecutorRunError


class RecordingCliShellRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result_path: Path | None = None
        self.last_message_text: str | None = None
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""

    def __call__(self, command, cwd, env, timeout_seconds, input_text=None):
        self.calls.append(
            {
                "command": list(command),
                "cwd": str(cwd) if cwd is not None else None,
                "env": dict(env or {}),
                "timeout_seconds": timeout_seconds,
                "input_text": input_text,
            }
        )
        if self.last_message_text is not None and "--output-last-message" in command:
            last_message_index = command.index("--output-last-message") + 1
            Path(command[last_message_index]).write_text(self.last_message_text, encoding="utf-8")
        if self.result_path is not None:
            self.result_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "summary": "Applied README update",
                        "changed_files": ["README.md"],
                        "checks": [],
                        "follow_up": [],
                    }
                ),
                encoding="utf-8",
            )
        return type(
            "Completed",
            (),
            {"returncode": self.returncode, "stdout": self.stdout, "stderr": self.stderr},
        )()


class CodexCliRunnerTests(unittest.TestCase):
    def test_run_and_wait_executes_codex_and_loads_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "repo"
            workspace.mkdir()
            result_path = workspace / "executor-result.json"
            shell_runner = RecordingCliShellRunner()
            shell_runner.result_path = result_path
            runner = CodexCliRunner(shell_runner=shell_runner)
            request = ExecutorRequest(
                workspace_path=str(workspace.resolve()),
                task_prompt="Update README",
                constraints=["keep changes minimal"],
                artifacts={"result_path": str(result_path)},
                label="task-1",
            )

            outcome = runner.run_and_wait(
                request,
                result_path=result_path,
                timeout_seconds=30,
            )

            self.assertEqual("completed", outcome.result.status)
            command = shell_runner.calls[0]["command"]
            expected_command = "codex.cmd" if os.name == "nt" else "codex"
            self.assertEqual(expected_command, command[0])
            self.assertIn("exec", command)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertEqual("-", command[-1])
            self.assertEqual(str(workspace.resolve()), shell_runner.calls[0]["cwd"])
            self.assertIn("Update README", shell_runner.calls[0]["input_text"])

    def test_run_and_wait_raises_when_result_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "repo"
            workspace.mkdir()
            result_path = workspace / "missing-result.json"
            shell_runner = RecordingCliShellRunner()
            runner = CodexCliRunner(shell_runner=shell_runner)
            request = ExecutorRequest(
                workspace_path=str(workspace.resolve()),
                task_prompt="Update README",
                artifacts={"result_path": str(result_path)},
            )

            with self.assertRaises(ExecutorRunError):
                runner.run_and_wait(
                    request,
                    result_path=result_path,
                    timeout_seconds=30,
                )

    def test_run_and_wait_recovers_json_from_last_message_when_result_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "repo"
            workspace.mkdir()
            result_path = workspace / "missing-result.json"
            shell_runner = RecordingCliShellRunner()
            shell_runner.last_message_text = """```json
{
  "status": "completed",
  "summary": "Recovered from the final response JSON.",
  "changed_files": ["README.md"],
  "checks": [],
  "follow_up": ["open PR"]
}
```"""
            runner = CodexCliRunner(shell_runner=shell_runner)
            request = ExecutorRequest(
                workspace_path=str(workspace.resolve()),
                task_prompt="Update README",
                artifacts={"result_path": str(result_path)},
            )

            outcome = runner.run_and_wait(
                request,
                result_path=result_path,
                timeout_seconds=30,
            )

            self.assertEqual("completed", outcome.result.status)
            self.assertEqual(["README.md"], outcome.result.changed_files)
            self.assertEqual(["open PR"], outcome.result.follow_up)
            self.assertTrue(result_path.exists())

    def test_run_and_wait_recovers_string_checks_as_informational_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "repo"
            workspace.mkdir()
            result_path = workspace / "missing-result.json"
            shell_runner = RecordingCliShellRunner()
            shell_runner.last_message_text = """```json
{
  "status": "completed",
  "summary": "Recovered from a planner-style final response.",
  "changed_files": ["README.md"],
  "checks": ["confirm README title", "append Result section"],
  "follow_up": []
}
```"""
            runner = CodexCliRunner(shell_runner=shell_runner)
            request = ExecutorRequest(
                workspace_path=str(workspace.resolve()),
                task_prompt="Plan the validation task",
                artifacts={"result_path": str(result_path)},
            )

            outcome = runner.run_and_wait(
                request,
                result_path=result_path,
                timeout_seconds=30,
            )

            self.assertEqual("completed", outcome.result.status)
            self.assertEqual("confirm README title", outcome.result.checks[0]["name"])
            self.assertEqual("informational", outcome.result.checks[0]["status"])

    def test_run_and_wait_synthesizes_result_from_prose_last_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "repo"
            workspace.mkdir()
            result_path = workspace / "missing-result.json"
            shell_runner = RecordingCliShellRunner()
            shell_runner.last_message_text = (
                "The plan is saved at [task-plan.md](D:/tmp/task-plan.md).\n\n"
                "It covers a documentation-only validation path, says the change is ready for execution, "
                "and lists the required preflight checks."
            )
            runner = CodexCliRunner(shell_runner=shell_runner)
            request = ExecutorRequest(
                workspace_path=str(workspace.resolve()),
                task_prompt="Plan the validation task",
                artifacts={"result_path": str(result_path)},
            )

            outcome = runner.run_and_wait(
                request,
                result_path=result_path,
                timeout_seconds=30,
            )

            self.assertEqual("completed", outcome.result.status)
            self.assertIn("The plan is saved", outcome.result.summary)
            self.assertEqual([], outcome.result.changed_files)
            self.assertTrue(result_path.exists())

    def test_windows_prefers_cmd_shim_when_available(self) -> None:
        shell_runner = RecordingCliShellRunner()
        with patch("codex_acp_runner.runner.os.name", "nt"), patch(
            "codex_acp_runner.runner.shutil.which",
            side_effect=lambda candidate: "C:/Users/lus/AppData/Roaming/npm/codex.cmd" if candidate == "codex.cmd" else None,
        ):
            runner = CodexCliRunner(shell_runner=shell_runner)

        self.assertEqual("codex.cmd", runner.codex_command)


if __name__ == "__main__":
    unittest.main()
