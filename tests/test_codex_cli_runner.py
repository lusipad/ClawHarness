from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_acp_runner import CodexCliRunner, ExecutorRequest, ExecutorRunError


class RecordingCliShellRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result_path: Path | None = None
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""

    def __call__(self, command, cwd, env, timeout_seconds):
        self.calls.append(
            {
                "command": list(command),
                "cwd": str(cwd) if cwd is not None else None,
                "env": dict(env or {}),
                "timeout_seconds": timeout_seconds,
            }
        )
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
            self.assertEqual("codex", command[0])
            self.assertIn("exec", command)
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertEqual(str(workspace.resolve()), shell_runner.calls[0]["cwd"])

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


if __name__ == "__main__":
    unittest.main()
