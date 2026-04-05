from __future__ import annotations

import json
import unittest

from rocketchat_notifier import NotificationMessage, RocketChatNotifier, RocketChatNotifierError


class RecordingTransport:
    def __init__(self, status_code: int = 200, response_body: bytes | None = None) -> None:
        self.status_code = status_code
        self.response_body = response_body or b'{"success":true}'
        self.calls: list[dict] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
            }
        )
        return self.status_code, {"Content-Type": "application/json"}, self.response_body


class RocketChatNotifierTests(unittest.TestCase):
    def test_message_payload_keeps_text_and_attachments(self) -> None:
        message = NotificationMessage(
            text="Task started",
            channel="#ai-dev",
            alias="Harness",
            emoji=":robot_face:",
            attachments=[{"title": "Task Started"}],
        )

        payload = message.to_payload()

        self.assertEqual("Task started", payload["text"])
        self.assertEqual("#ai-dev", payload["channel"])
        self.assertEqual("Harness", payload["alias"])
        self.assertEqual(":robot_face:", payload["emoji"])
        self.assertEqual([{"title": "Task Started"}], payload["attachments"])

    def test_build_lifecycle_message_adds_standard_fields(self) -> None:
        notifier = RocketChatNotifier(webhook_url="https://chat.example/hooks/1/abc", default_channel="#ai-dev")

        message = notifier.build_lifecycle_message(
            event_type="pr_opened",
            task_key="AB#123",
            run_id="run-1",
            summary="PR opened for task AB#123",
            details={"pr_url": "https://ado/pr/1"},
        )

        attachment = message.attachments[0]
        self.assertEqual("Pr Opened", attachment["title"])
        self.assertEqual("#2eb67d", attachment["color"])
        self.assertEqual("#ai-dev", message.channel)
        self.assertEqual("AB#123", attachment["fields"][0]["value"])
        self.assertEqual("run-1", attachment["fields"][1]["value"])

    def test_post_message_sends_json_payload(self) -> None:
        transport = RecordingTransport()
        notifier = RocketChatNotifier(
            webhook_url="https://chat.example/hooks/1/abc",
            default_channel="#ai-dev",
            transport=transport,
        )

        result = notifier.notify_lifecycle(
            event_type="task_started",
            task_key="AB#123",
            run_id="run-1",
            summary="Task claimed",
            details={"owner": "worker-a"},
        )

        self.assertEqual({"success": True}, result)
        call = transport.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertEqual("https://chat.example/hooks/1/abc", call["url"])
        payload = json.loads(call["body"].decode("utf-8"))
        self.assertEqual("Task claimed", payload["text"])
        self.assertEqual("#ai-dev", payload["channel"])
        self.assertEqual("ClawHarness", payload["alias"])

    def test_post_message_raises_on_http_failure(self) -> None:
        transport = RecordingTransport(status_code=500, response_body=b'{"error":"bad"}')
        notifier = RocketChatNotifier(
            webhook_url="https://chat.example/hooks/1/abc",
            transport=transport,
        )

        with self.assertRaises(RocketChatNotifierError):
            notifier.post_message(NotificationMessage(text="broken"))


if __name__ == "__main__":
    unittest.main()
