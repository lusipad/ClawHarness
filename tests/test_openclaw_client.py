from __future__ import annotations

import json
import unittest

from harness_runtime import OpenClawWebhookClient, OpenClawWebhookError


class RecordingTransport:
    def __init__(self, status_code: int = 200, body: bytes | None = None) -> None:
        self.status_code = status_code
        self.body = body or b'{"ok":true}'
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
        return self.status_code, {"Content-Type": "application/json"}, self.body


class OpenClawWebhookClientTests(unittest.TestCase):
    def test_run_agent_posts_expected_payload(self) -> None:
        transport = RecordingTransport()
        client = OpenClawWebhookClient(
            base_url="http://127.0.0.1:18789",
            token="secret",
            path="/hooks",
            transport=transport,
        )

        result = client.run_agent(
            message="Handle task AB#123",
            name="Azure DevOps Task",
            agent_id="hooks",
            session_key="hook:harness:task:AB-123",
            wake_mode="now",
            deliver=False,
            timeout_seconds=120,
        )

        self.assertEqual({"ok": True}, result)
        call = transport.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertEqual("http://127.0.0.1:18789/hooks/agent", call["url"])
        self.assertEqual("Bearer secret", call["headers"]["Authorization"])
        payload = json.loads(call["body"].decode("utf-8"))
        self.assertEqual("hooks", payload["agentId"])
        self.assertEqual("hook:harness:task:AB-123", payload["sessionKey"])

    def test_wake_posts_to_wake_endpoint(self) -> None:
        transport = RecordingTransport()
        client = OpenClawWebhookClient(
            base_url="http://127.0.0.1:18789",
            token="secret",
            transport=transport,
        )

        client.wake("wake up", mode="now")

        call = transport.calls[0]
        self.assertEqual("http://127.0.0.1:18789/hooks/wake", call["url"])

    def test_invoke_tool_posts_to_tools_invoke_endpoint(self) -> None:
        transport = RecordingTransport(body=b'{"ok":true,"result":{"accepted":true,"sessionId":"session-1"}}')
        client = OpenClawWebhookClient(
            base_url="http://127.0.0.1:18789",
            token="secret",
            transport=transport,
        )

        result = client.invoke_tool(
            tool="sessions_spawn",
            action="session_spawn",
            session_key="agent:main:main",
            args={"runtime": "acp", "task": "Implement"},
        )

        self.assertEqual({"accepted": True, "sessionId": "session-1"}, result)
        call = transport.calls[0]
        self.assertEqual("http://127.0.0.1:18789/tools/invoke", call["url"])
        payload = json.loads(call["body"].decode("utf-8"))
        self.assertEqual("sessions_spawn", payload["tool"])
        self.assertEqual("session_spawn", payload["action"])
        self.assertEqual("agent:main:main", payload["sessionKey"])

    def test_http_error_raises(self) -> None:
        client = OpenClawWebhookClient(
            base_url="http://127.0.0.1:18789",
            token="secret",
            transport=RecordingTransport(status_code=500, body=b"boom"),
        )

        with self.assertRaises(OpenClawWebhookError):
            client.wake("wake up")


if __name__ == "__main__":
    unittest.main()
