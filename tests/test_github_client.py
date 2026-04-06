from __future__ import annotations

import json
import unittest

from github_client import GitHubRestClient


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses: list[tuple[int, dict[str, str], bytes]] = []

    def queue_json(self, payload) -> None:
        self.responses.append((200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")))

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if not self.responses:
            return 200, {"Content-Type": "application/json"}, b"{}"
        return self.responses.pop(0)


class GitHubRestClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = RecordingTransport()
        self.client = GitHubRestClient(token="github-token", transport=self.transport)

    def test_get_task_maps_issue_to_shared_task_context(self) -> None:
        self.transport.queue_json(
            {
                "number": 42,
                "title": "Implement GitHub adapter",
                "body": "Make the workflow provider-neutral.",
                "state": "open",
                "html_url": "https://github.com/lusipad/ClawHarness/issues/42",
                "labels": [{"name": "runtime"}],
                "assignees": [{"login": "alice"}],
            }
        )

        task = self.client.get_task("42", repo_id="lusipad/ClawHarness")

        self.assertEqual("lusipad/ClawHarness", task["fields"]["System.TeamProject"])
        self.assertEqual("Implement GitHub adapter", task["fields"]["System.Title"])
        self.assertEqual(["runtime"], task["fields"]["GitHub.Labels"])
        self.assertEqual(["alice"], task["fields"]["GitHub.Assignees"])
        self.assertIn("/repos/lusipad/ClawHarness/issues/42", self.transport.calls[0]["url"])
        self.assertEqual("Bearer github-token", self.transport.calls[0]["headers"]["Authorization"])

    def test_normalize_issue_comment_on_pull_request_becomes_pr_feedback_event(self) -> None:
        event = self.client.normalize_event(
            event_type="issue_comment",
            source_id="delivery-1",
            payload={
                "action": "created",
                "issue": {"number": 15, "pull_request": {"url": "https://api.github.com/repos/x/pulls/15"}},
                "repository": {"full_name": "lusipad/ClawHarness"},
                "sender": {"login": "reviewer", "id": 9},
            },
        )

        self.assertEqual("pr.comment.created", event.event_type)
        self.assertEqual("github", event.provider_type)
        self.assertEqual("15", event.pr_id)
        self.assertEqual("lusipad/ClawHarness", event.repo_id)
        self.assertEqual("reviewer", event.actor["name"])

    def test_normalize_check_run_failure_prefixes_ci_run_id_and_keeps_pr_link(self) -> None:
        event = self.client.normalize_event(
            event_type="check_run",
            source_id="delivery-2",
            payload={
                "action": "completed",
                "check_run": {
                    "id": 201,
                    "conclusion": "failure",
                    "pull_requests": [{"number": 15}],
                },
                "repository": {"full_name": "lusipad/ClawHarness"},
            },
        )

        self.assertEqual("ci.run.failed", event.event_type)
        self.assertEqual("check-run:201", event.ci_run_id)
        self.assertEqual("15", event.pr_id)

    def test_list_pull_request_comments_merges_review_and_issue_comments(self) -> None:
        self.transport.queue_json(
            [
                {
                    "id": 31,
                    "body": "review comment",
                    "created_at": "2026-04-05T12:00:00Z",
                    "updated_at": "2026-04-05T12:00:01Z",
                    "user": {"login": "alice"},
                    "in_reply_to_id": None,
                }
            ]
        )
        self.transport.queue_json(
            [
                {
                    "id": 41,
                    "body": "issue comment",
                    "created_at": "2026-04-05T12:00:02Z",
                    "updated_at": "2026-04-05T12:00:03Z",
                    "user": {"login": "bob"},
                }
            ]
        )

        comments = self.client.list_pull_request_comments("lusipad/ClawHarness", "15")

        self.assertEqual(2, len(comments))
        self.assertEqual("review", comments[0]["comment_type"])
        self.assertEqual("issue", comments[1]["comment_type"])
        self.assertEqual("issue-comment:41", comments[1]["thread_id"])

    def test_retry_ci_run_rerequests_check_run(self) -> None:
        self.transport.queue_json({})

        response = self.client.retry_ci_run("check-run:201", repo_id="lusipad/ClawHarness")

        self.assertEqual("check-run:201", response["id"])
        self.assertEqual("POST", self.transport.calls[0]["method"])
        self.assertIn("/repos/lusipad/ClawHarness/check-runs/201/rerequest", self.transport.calls[0]["url"])


if __name__ == "__main__":
    unittest.main()
