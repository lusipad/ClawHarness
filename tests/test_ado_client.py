from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path

from ado_client import AzureDevOpsRestClient


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses: list[tuple[int, dict[str, str], bytes]] = []

    def queue_json(self, payload: dict) -> None:
        self.responses.append((200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")))

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict[str, str], bytes]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
            }
        )
        if not self.responses:
            raise AssertionError("No queued response for request")
        return self.responses.pop(0)


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


class AzureDevOpsRestClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = RecordingTransport()
        self.shell_runner = RecordingShellRunner()
        self.client = AzureDevOpsRestClient(
            base_url="https://dev.azure.com/example-org",
            project="ExampleProject",
            pat="secret",
            transport=self.transport,
            shell_runner=self.shell_runner,
        )

    def test_get_task_uses_work_item_endpoint(self) -> None:
        self.transport.queue_json({"id": 123})

        response = self.client.get_task(123, fields=["System.Title"], expand="relations")

        self.assertEqual({"id": 123}, response)
        call = self.transport.calls[0]
        self.assertEqual("GET", call["method"])
        self.assertIn("/ExampleProject/_apis/wit/workitems/123?", call["url"])
        self.assertIn("fields=System.Title", call["url"])
        self.assertIn("$expand=relations", call["url"])

    def test_update_task_fields_uses_json_patch(self) -> None:
        self.transport.queue_json({"id": 123, "rev": 2})

        self.client.update_task_fields(
            123,
            [
                {"op": "add", "path": "/fields/System.State", "value": "Active"},
            ],
            bypass_rules=True,
        )

        call = self.transport.calls[0]
        self.assertEqual("PATCH", call["method"])
        self.assertEqual("application/json-patch+json", call["headers"]["Content-Type"])
        self.assertIn("bypassRules=true", call["url"])
        self.assertEqual(
            [{"op": "add", "path": "/fields/System.State", "value": "Active"}],
            json.loads(call["body"].decode("utf-8")),
        )

    def test_add_task_comment_uses_preview_comment_api(self) -> None:
        self.transport.queue_json({"id": 50, "text": "hello"})

        self.client.add_task_comment(123, "hello")

        call = self.transport.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertIn("/_apis/wit/workItems/123/comments?", call["url"])
        self.assertIn("api-version=7.0-preview.3", call["url"])
        self.assertEqual({"text": "hello"}, json.loads(call["body"].decode("utf-8")))

    def test_complete_task_updates_state_and_posts_comment(self) -> None:
        self.transport.queue_json({"id": 123, "fields": {"System.State": "Done"}})
        self.transport.queue_json({"id": 50, "text": "done"})

        response = self.client.complete_task(123, comment="done")

        self.assertEqual("Done", response["fields"]["System.State"])
        patch_call = self.transport.calls[0]
        comment_call = self.transport.calls[1]
        self.assertEqual("PATCH", patch_call["method"])
        self.assertEqual(
            [{"op": "add", "path": "/fields/System.State", "value": "Done"}],
            json.loads(patch_call["body"].decode("utf-8")),
        )
        self.assertEqual("POST", comment_call["method"])
        self.assertIn("/_apis/wit/workItems/123/comments?", comment_call["url"])

    def test_create_pull_request_builds_expected_payload(self) -> None:
        self.transport.queue_json({"pullRequestId": 42})

        self.client.create_pull_request(
            "repo-1",
            source_branch="refs/heads/ai/task-1",
            target_branch="refs/heads/main",
            title="AI task",
            description="OpenClaw generated change",
            reviewers=[{"id": "user-1"}],
            supports_iterations=True,
        )

        call = self.transport.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertIn("/_apis/git/repositories/repo-1/pullrequests?", call["url"])
        self.assertIn("supportsIterations=true", call["url"])
        self.assertEqual(
            {
                "sourceRefName": "refs/heads/ai/task-1",
                "targetRefName": "refs/heads/main",
                "title": "AI task",
                "description": "OpenClaw generated change",
                "reviewers": [{"id": "user-1"}],
            },
            json.loads(call["body"].decode("utf-8")),
        )

    def test_reply_to_pull_request_posts_thread_comment(self) -> None:
        self.transport.queue_json({"id": 7})

        self.client.reply_to_pull_request("repo-1", 42, thread_id=8, content="Applied", parent_comment_id=1)

        call = self.transport.calls[0]
        self.assertIn("/pullRequests/42/threads/8/comments?", call["url"])
        self.assertEqual(
            {"content": "Applied", "parentCommentId": 1, "commentType": 1},
            json.loads(call["body"].decode("utf-8")),
        )

    def test_retry_build_queues_new_build_from_existing_metadata(self) -> None:
        self.transport.queue_json(
            {
                "id": 100,
                "definition": {"id": 55},
                "sourceBranch": "refs/heads/ai/task-1",
                "sourceVersion": "abc123",
                "parameters": "{\"runMode\":\"retry\"}",
            }
        )
        self.transport.queue_json({"id": 101})

        retried = self.client.retry_build(100)

        self.assertEqual({"id": 101}, retried)
        self.assertEqual("GET", self.transport.calls[0]["method"])
        self.assertEqual("POST", self.transport.calls[1]["method"])
        queued_body = json.loads(self.transport.calls[1]["body"].decode("utf-8"))
        self.assertEqual(
            {
                "definition": {"id": 55},
                "sourceBranch": "refs/heads/ai/task-1",
                "sourceVersion": "abc123",
                "parameters": "{\"runMode\":\"retry\"}",
            },
            queued_body,
        )

    def test_retry_ci_run_requeues_latest_branch_tip_without_source_version(self) -> None:
        self.transport.queue_json(
            {
                "id": 100,
                "definition": {"id": 55},
                "sourceBranch": "refs/heads/ai/task-1",
                "sourceVersion": "abc123",
                "parameters": "{\"runMode\":\"retry\"}",
                "queue": {"id": 38},
            }
        )
        self.transport.queue_json({"id": 101})

        retried = self.client.retry_ci_run(100)

        self.assertEqual({"id": 101}, retried)
        self.assertEqual("GET", self.transport.calls[0]["method"])
        self.assertEqual("POST", self.transport.calls[1]["method"])
        queued_body = json.loads(self.transport.calls[1]["body"].decode("utf-8"))
        self.assertEqual(
            {
                "definition": {"id": 55},
                "sourceBranch": "refs/heads/ai/task-1",
                "parameters": "{\"runMode\":\"retry\"}",
                "queue": {"id": 38},
            },
            queued_body,
        )

    def test_get_repository_reads_repository_metadata(self) -> None:
        self.transport.queue_json(
            {
                "id": "repo-1",
                "name": "AI-Review-Test",
                "defaultBranch": "refs/heads/main",
                "remoteUrl": "https://dev.azure.com/example-org/ExampleProject/_git/AI-Review-Test",
                "webUrl": "https://dev.azure.com/example-org/ExampleProject/_git/AI-Review-Test",
            }
        )

        repository = self.client.get_repository("repo-1")

        self.assertEqual("repo-1", repository.repository_id)
        self.assertEqual("AI-Review-Test", repository.name)
        self.assertEqual("refs/heads/main", repository.default_branch)

    def test_prepare_workspace_clones_run_specific_directory(self) -> None:
        self.transport.queue_json(
            {
                "id": "repo-1",
                "name": "AI Review Test",
                "defaultBranch": "refs/heads/main",
                "remoteUrl": "https://dev.azure.com/example-org/ExampleProject/_git/AI-Review-Test",
            }
        )
        self.shell_runner.queue()

        result = self.client.prepare_workspace("repo-1", workspace_root="D:/Repos/workspaces", run_id="run/123")

        self.assertEqual("refs/heads/main", result.base_branch)
        self.assertTrue(result.workspace_path.endswith("AI-Review-Test-run-123"))
        call = self.shell_runner.calls[0]
        command = call["command"]
        self.assertIn("clone", command)
        self.assertIn("--branch", command)
        self.assertIn("main", command)

    def test_create_branch_fetches_and_checks_out_base_branch(self) -> None:
        self.shell_runner.queue()
        self.shell_runner.queue()

        branch_ref = self.client.create_branch(
            "D:/Repos/workspaces/repo-run-1",
            branch_name="ai/task-1",
            base_branch="refs/heads/main",
        )

        self.assertEqual("refs/heads/ai/task-1", branch_ref)
        fetch_command = self.shell_runner.calls[0]["command"]
        checkout_command = self.shell_runner.calls[1]["command"]
        self.assertIn("fetch", fetch_command)
        self.assertIn("refs/heads/main", fetch_command)
        self.assertIn("checkout", checkout_command)
        self.assertIn("ai/task-1", checkout_command)
        self.assertIn("origin/main", checkout_command)

    def test_commit_and_push_stages_commits_and_pushes_branch(self) -> None:
        self.shell_runner.queue(stdout=" M README.md\n")
        self.shell_runner.queue()
        self.shell_runner.queue()
        self.shell_runner.queue(stdout="abc123\n")
        self.shell_runner.queue()

        result = self.client.commit_and_push(
            "D:/Repos/workspaces/repo-run-1",
            branch_name="ai/task-1",
            commit_message="OpenClaw test commit",
        )

        self.assertTrue(result.created_commit)
        self.assertEqual("abc123", result.commit_sha)
        commands = [call["command"] for call in self.shell_runner.calls]
        self.assertEqual("status", commands[0][1])
        self.assertEqual("add", commands[1][1])
        self.assertEqual("commit", commands[2][5])
        self.assertEqual("rev-parse", commands[3][1])
        self.assertIn("HEAD:refs/heads/ai/task-1", commands[4])

    def test_normalize_event_extracts_common_fields(self) -> None:
        normalized = self.client.normalize_event(
            event_type="task.updated",
            source_id="evt-1",
            payload={
                "resource": {
                    "id": 123,
                    "fields": {
                        "System.TeamProject": "AB",
                    },
                    "revisedBy": {
                        "id": "user-1",
                        "displayName": "Alice",
                    },
                },
                "resourceContainers": {
                    "repository": {
                        "id": "repo-1",
                    }
                },
            },
        )

        self.assertEqual("123", normalized.task_id)
        self.assertEqual("AB#123", normalized.task_key)
        self.assertEqual("repo-1", normalized.repo_id)
        self.assertEqual({"id": "user-1", "name": "Alice"}, normalized.actor)

    def test_normalize_event_maps_completed_pull_request_to_pr_merged(self) -> None:
        normalized = self.client.normalize_event(
            event_type="git.pullrequest.updated",
            source_id="evt-pr-merged",
            payload={
                "resource": {
                    "pullRequestId": 42,
                    "status": "completed",
                    "mergeStatus": "succeeded",
                    "repository": {"id": "repo-1"},
                }
            },
        )

        self.assertEqual("pr.merged", normalized.event_type)
        self.assertEqual("42", normalized.pr_id)
        self.assertEqual("repo-1", normalized.repo_id)

    def test_authorization_header_uses_basic_pat(self) -> None:
        self.transport.queue_json({"id": 123})

        self.client.get_task(123)

        auth = self.transport.calls[0]["headers"]["Authorization"]
        expected = base64.b64encode(b":secret").decode("ascii")
        self.assertEqual(f"Basic {expected}", auth)


if __name__ == "__main__":
    unittest.main()
