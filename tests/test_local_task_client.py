from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from local_client import LocalTaskClient


class RecordingShellRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses: list[tuple[int, str, str]] = []

    def queue(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((returncode, stdout, stderr))

    def __call__(self, command: list[str], cwd: str | Path | None, env: dict[str, str] | None):
        self.calls.append({"command": command, "cwd": str(cwd) if cwd is not None else None, "env": env})
        if not self.responses:
            raise AssertionError("No queued shell response")
        returncode, stdout, stderr = self.responses.pop(0)
        return type(
            "Completed",
            (),
            {"returncode": returncode, "stdout": stdout, "stderr": stderr},
        )()


class LocalTaskClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.tasks = self.base / "tasks"
        self.tasks.mkdir()
        self.reviews = self.base / "reviews"
        self.reviews.mkdir()
        (self.tasks / "task-1.md").write_text("# Fix offline mode\n\nMake the deployment package work offline.\n", encoding="utf-8")
        self.shell_runner = RecordingShellRunner()
        self.client = LocalTaskClient(
            repository_path=self.repo,
            task_directory=self.tasks,
            review_directory=self.reviews,
            base_branch="main",
            push_enabled=False,
            shell_runner=self.shell_runner,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_get_task_reads_markdown_file(self) -> None:
        task = self.client.get_task("task-1", repo_id=str(self.repo))

        self.assertEqual("task-1", task["id"])
        self.assertEqual("repo", task["fields"]["System.TeamProject"])
        self.assertEqual("Fix offline mode", task["fields"]["System.Title"])
        self.assertIn("deployment package work offline", task["fields"]["System.Description"])
        self.assertEqual(str(self.tasks / "task-1.md"), task["fields"]["LocalTask.FilePath"])

    def test_prepare_workspace_and_commit_skip_push_when_disabled(self) -> None:
        workspace_root = self.base / "workspaces"
        self.shell_runner.queue()
        self.shell_runner.queue()
        self.shell_runner.queue()
        self.shell_runner.queue(stdout=" M README.md\n")
        self.shell_runner.queue()
        self.shell_runner.queue()
        self.shell_runner.queue(stdout="abc123\n")

        preparation = self.client.prepare_workspace(str(self.repo), workspace_root=workspace_root, run_id="run-1")
        branch_ref = self.client.create_branch(preparation.workspace_path, branch_name="ai/task-1", base_branch="main")
        publish = self.client.commit_and_push(preparation.workspace_path, branch_name=branch_ref, commit_message="offline task")

        self.assertEqual("refs/heads/main", preparation.base_branch)
        self.assertEqual("refs/heads/ai/task-1", branch_ref)
        self.assertEqual("abc123", publish.commit_sha)
        commands = [call["command"] for call in self.shell_runner.calls]
        self.assertEqual(["git", "clone", "--origin", "origin", "--branch", "main", str(self.repo), str(workspace_root / "repo-run-1")], commands[0])
        self.assertEqual(["git", "fetch", "origin", "refs/heads/main"], commands[1])
        self.assertEqual(["git", "checkout", "-B", "ai/task-1", "origin/main"], commands[2])
        self.assertNotIn(["git", "push", "-u", "origin", "HEAD:refs/heads/ai/task-1"], commands)

    def test_create_pull_request_writes_local_review_artifact(self) -> None:
        payload = self.client.create_pull_request(
            str(self.repo),
            source_branch="refs/heads/ai/task-1",
            target_branch="refs/heads/main",
            title="repo#task-1: Fix offline mode",
            description="Review the offline deployment changes.",
        )

        review_path = Path(payload["url"])
        self.assertTrue(review_path.exists())
        contents = review_path.read_text(encoding="utf-8")
        self.assertIn("Fix offline mode", contents)
        self.assertIn("No remote PR platform was contacted.", contents)

    def test_complete_task_writes_state_and_comment(self) -> None:
        payload = self.client.complete_task("task-1", comment="offline review accepted")

        state_path = Path(payload["path"])
        self.assertTrue(state_path.exists())
        self.assertEqual("completed", json.loads(state_path.read_text(encoding="utf-8"))["state"])
        comments_path = self.reviews / "task-comments" / "task-1.jsonl"
        self.assertTrue(comments_path.exists())
        self.assertIn("offline review accepted", comments_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
