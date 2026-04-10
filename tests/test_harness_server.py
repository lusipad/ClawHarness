from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from harness_runtime.bridge import BridgeResult, ChatCommandResult
from harness_runtime.server import create_handler
from run_store import RunStore, TaskRun


class DummyBridge:
    def __init__(self, store: RunStore) -> None:
        self.store = store
        self.chat_calls: list[dict[str, object]] = []
        self.github_calls: list[dict[str, object]] = []

    def handle_ado_event(self, *, event_type: str, payload: dict[str, object], source_id: str | None = None):
        raise NotImplementedError

    def handle_github_event(self, *, event_type: str, payload: dict[str, object], source_id: str | None = None):
        self.github_calls.append({"event_type": event_type, "payload": dict(payload), "source_id": source_id})
        return BridgeResult(accepted=True, action="task_dispatched", run_id="run-gh", session_key="session-gh")

    def handle_chat_command(self, *, provider_type: str, payload: dict[str, object]) -> ChatCommandResult:
        self.chat_calls.append({"provider_type": provider_type, "payload": dict(payload)})
        return ChatCommandResult(
            ok=True,
            command="status",
            text="chat ok",
            run_id="run-chat",
            attachments=[{"title": "status", "fields": [{"title": "Run", "value": "run-chat", "short": True}]}],
        )


def make_run(*, run_id: str, task_key: str, status: str, updated_at: str) -> TaskRun:
    return TaskRun(
        run_id=run_id,
        provider_type="azure-devops",
        task_id=task_key.split("#")[-1],
        task_key=task_key,
        session_id=f"session-{run_id}",
        executor_type="codex-cli",
        status=status,
        repo_id="repo-1",
        started_at="2026-04-05T12:00:00Z",
        updated_at=updated_at,
    )


class HarnessServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "harness.db"
        self.store = RunStore(self.db_path)
        self.store.initialize()

        run_1 = self.store.create_run(
            make_run(
                run_id="run-1",
                task_key="AB#101",
                status="awaiting_review",
                updated_at="2026-04-05T12:10:00Z",
            )
        )
        run_2 = self.store.create_run(
            make_run(
                run_id="run-2",
                task_key="AB#102",
                status="awaiting_human",
                updated_at="2026-04-05T12:05:00Z",
            )
        )
        self.store.append_audit(run_1.run_id, "run_claimed", payload={"task_key": run_1.task_key})
        self.store.append_audit(run_1.run_id, "executor_completed", payload={"status": "completed"})
        self.store.append_audit(run_2.run_id, "run_blocked", payload={"reason": "needs_human"})
        self.store.link_runs(run_1.run_id, run_2.run_id, relation_type="agent-executor", created_at="2026-04-05T12:11:00Z")
        self.store.record_checkpoint(
            run_1.run_id,
            "workspace_prepared",
            payload={"workspace_path": "/tmp/run-1"},
            created_at="2026-04-05T12:12:00Z",
        )
        self.store.record_artifact(
            run_1.run_id,
            "executor-result",
            "task-result.json",
            path="/tmp/task-result.json",
            payload={"status": "completed"},
            created_at="2026-04-05T12:13:00Z",
        )
        self.store.record_checkpoint(
            run_2.run_id,
            "agent_completed",
            payload={"agent_role": "executor", "status": "completed"},
            created_at="2026-04-05T12:14:00Z",
        )
        self.store.record_artifact(
            run_2.run_id,
            "executor-result",
            "executor-child.json",
            path="/tmp/run-2.json",
            payload={"status": "completed", "summary": "Implemented the requested patch."},
            created_at="2026-04-05T12:15:00Z",
        )
        self.store.record_skill_selection(
            run_2.run_id,
            parent_run_id=run_1.run_id,
            run_kind="task",
            agent_role="executor",
            registry_version="2026-04-06",
            selection_key="task:executor:azure-devops",
            payload={"matched_skills": [{"skill_id": "implement-task"}]},
            created_at="2026-04-05T12:16:00Z",
        )

        self.bridge = DummyBridge(self.store)
        handler = create_handler(self.bridge, ingress_token="ingress-secret")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _get_json(self, path: str, *, token: str | None = None) -> tuple[int, dict[str, object]]:
        request = Request(f"http://127.0.0.1:{self.port}{path}")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urlopen(request, timeout=5) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            exc.close()
            return int(exc.code), json.loads(body)

    def _post_json(
        self,
        path: str,
        *,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        request = Request(f"http://127.0.0.1:{self.port}{path}", data=body, method="POST")
        request.add_header("Content-Type", content_type)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urlopen(request, timeout=5) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8")
            exc.close()
            return int(exc.code), json.loads(payload)

    def test_api_runs_requires_token_when_configured(self) -> None:
        status, payload = self._get_json("/api/runs")

        self.assertEqual(401, status)
        self.assertEqual("unauthorized", payload["error"])

    def test_api_can_use_dedicated_readonly_token(self) -> None:
        handler = create_handler(DummyBridge(self.store), ingress_token="ingress-secret", readonly_token="readonly-secret")
        extra_httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=extra_httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{extra_httpd.server_address[1]}/api/runs")
            request.add_header("Authorization", "Bearer readonly-secret")
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(2, payload["count"])
        finally:
            extra_httpd.shutdown()
            extra_httpd.server_close()
            thread.join(timeout=5)

    def test_api_can_use_control_token_for_read_access(self) -> None:
        handler = create_handler(DummyBridge(self.store), ingress_token="ingress-secret", control_token="control-secret")
        extra_httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=extra_httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{extra_httpd.server_address[1]}/api/runs")
            request.add_header("Authorization", "Bearer control-secret")
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(2, payload["count"])
        finally:
            extra_httpd.shutdown()
            extra_httpd.server_close()
            thread.join(timeout=5)

    def test_api_runs_returns_summary_and_runs(self) -> None:
        status, payload = self._get_json("/api/runs?limit=1", token="ingress-secret")

        self.assertEqual(200, status)
        self.assertEqual(1, payload["count"])
        self.assertEqual(2, payload["summary"]["total_runs"])
        self.assertEqual(1, payload["summary"]["status_counts"]["awaiting_review"])
        self.assertEqual(["run-1"], [run["run_id"] for run in payload["runs"]])

    def test_api_runs_supports_status_and_task_key_filters(self) -> None:
        status, payload = self._get_json(
            "/api/runs?status=awaiting_human&task_key=AB%23102",
            token="ingress-secret",
        )

        self.assertEqual(200, status)
        self.assertEqual("awaiting_human", payload["filters"]["status"])
        self.assertEqual("AB#102", payload["filters"]["task_key"])
        self.assertEqual(["run-2"], [run["run_id"] for run in payload["runs"]])

    def test_api_runs_rejects_invalid_status(self) -> None:
        status, payload = self._get_json("/api/runs?status=not-real", token="ingress-secret")

        self.assertEqual(400, status)
        self.assertEqual("invalid_status", payload["error"])

    def test_api_run_detail_returns_run_and_audit_count(self) -> None:
        status, payload = self._get_json("/api/runs/run-1", token="ingress-secret")

        self.assertEqual(200, status)
        self.assertEqual("run-1", payload["run"]["run_id"])
        self.assertEqual(2, payload["audit_count"])

    def test_api_run_audit_returns_run_and_audit_chain(self) -> None:
        status, payload = self._get_json("/api/runs/run-1/audit", token="ingress-secret")

        self.assertEqual(200, status)
        self.assertEqual("run-1", payload["run"]["run_id"])
        self.assertEqual(["run_claimed", "executor_completed"], [item["event_type"] for item in payload["audit"]])
        self.assertEqual({"status": "completed"}, payload["audit"][1]["payload"])

    def test_api_run_graph_returns_parent_children_checkpoints_and_artifacts(self) -> None:
        status, payload = self._get_json("/api/runs/run-1/graph", token="ingress-secret")

        self.assertEqual(200, status)
        self.assertEqual("run-1", payload["run"]["run_id"])
        self.assertEqual(["run-2"], [item["run"]["run_id"] for item in payload["child_runs"]])
        self.assertEqual("agent-executor", payload["child_runs"][0]["relation_type"])
        self.assertEqual("executor", payload["child_runs"][0]["agent_role"])
        self.assertEqual("agent_completed", payload["child_runs"][0]["latest_checkpoint"]["stage"])
        self.assertEqual("Implemented the requested patch.", payload["child_runs"][0]["latest_conclusion"]["payload"]["summary"])
        self.assertEqual("workspace_prepared", payload["checkpoints"][0]["stage"])
        self.assertEqual({"workspace_path": "/tmp/run-1"}, payload["checkpoints"][0]["payload"])
        self.assertEqual("executor-result", payload["artifacts"][0]["artifact_type"])
        self.assertEqual({"status": "completed"}, payload["artifacts"][0]["payload"])
        self.assertEqual("task", payload["child_runs"][0]["skill_selections"][0]["run_kind"])
        self.assertEqual("executor", payload["child_runs"][0]["skill_selections"][0]["agent_role"])

    def test_chat_webhook_accepts_form_urlencoded_payload(self) -> None:
        status, payload = self._post_json(
            "/webhooks/chat/rocketchat",
            body=b"token=ingress-secret&text=status+run-1&channel_id=room-1",
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(200, status)
        self.assertEqual("chat ok", payload["text"])
        self.assertEqual("rocketchat", self.bridge.chat_calls[0]["provider_type"])
        self.assertEqual("status run-1", self.bridge.chat_calls[0]["payload"]["text"])
        self.assertEqual("room-1", self.bridge.chat_calls[0]["payload"]["channel_id"])

    def test_chat_webhook_prefers_dedicated_command_token(self) -> None:
        bridge = DummyBridge(self.store)
        handler = create_handler(
            bridge,
            ingress_token="ingress-secret",
            chat_command_token="chat-secret",
        )
        extra_httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=extra_httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{extra_httpd.server_address[1]}/webhooks/chat/rocketchat",
                data=json.dumps({"token": "ingress-secret", "text": "status run-1"}).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            with self.assertRaises(HTTPError) as ctx:
                urlopen(request, timeout=5)
            self.assertEqual(401, ctx.exception.code)
            ctx.exception.close()
            self.assertEqual([], bridge.chat_calls)
        finally:
            extra_httpd.shutdown()
            extra_httpd.server_close()
            thread.join(timeout=5)

    def test_weixin_chat_webhook_accepts_json_payload(self) -> None:
        status, payload = self._post_json(
            "/webhooks/chat/weixin",
            body=json.dumps(
                {
                    "token": "ingress-secret",
                    "command": "status",
                    "task_key": "AB#101",
                    "conversation_id": "wx-room-1",
                }
            ).encode("utf-8"),
            content_type="application/json",
        )

        self.assertEqual(200, status)
        self.assertEqual("chat ok", payload["text"])
        self.assertEqual("weixin", self.bridge.chat_calls[0]["provider_type"])
        self.assertEqual("status", self.bridge.chat_calls[0]["payload"]["command"])
        self.assertEqual("AB#101", self.bridge.chat_calls[0]["payload"]["task_key"])

    def test_api_run_command_requires_control_token_when_configured(self) -> None:
        bridge = DummyBridge(self.store)
        handler = create_handler(
            bridge,
            ingress_token="ingress-secret",
            control_token="control-secret",
        )
        extra_httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=extra_httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{extra_httpd.server_address[1]}/api/runs/run-1/command",
                data=json.dumps({"command": "pause"}).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            request.add_header("Authorization", "Bearer ingress-secret")
            try:
                urlopen(request, timeout=5)
                self.fail("Expected control token authorization to reject ingress token")
            except HTTPError as exc:
                status = int(exc.code)
                payload = json.loads(exc.read().decode("utf-8"))
                exc.close()
            self.assertEqual(401, status)
            self.assertEqual("unauthorized", payload["error"])
        finally:
            extra_httpd.shutdown()
            extra_httpd.server_close()
            thread.join(timeout=5)

    def test_api_run_command_dispatches_bot_view_payload(self) -> None:
        bridge = DummyBridge(self.store)
        handler = create_handler(
            bridge,
            ingress_token="ingress-secret",
            control_token="control-secret",
        )
        extra_httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=extra_httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{extra_httpd.server_address[1]}/api/runs/run-1/command",
                data=json.dumps({"command": "pause", "reason": "Need manual approval"}).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            request.add_header("Authorization", "Bearer control-secret")
            with urlopen(request, timeout=5) as response:
                status = int(response.status)
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(200, status)
            self.assertTrue(payload["ok"])
            self.assertEqual("bot-view", bridge.chat_calls[0]["provider_type"])
            self.assertEqual("pause", bridge.chat_calls[0]["payload"]["command"])
            self.assertEqual("run-1", bridge.chat_calls[0]["payload"]["run_id"])
            self.assertEqual("Need manual approval", bridge.chat_calls[0]["payload"]["reason"])
        finally:
            extra_httpd.shutdown()
            extra_httpd.server_close()
            thread.join(timeout=5)

    def test_github_webhook_validates_signature_and_dispatches_event(self) -> None:
        import hashlib
        import hmac

        bridge = DummyBridge(self.store)
        handler = create_handler(
            bridge,
            ingress_token="ingress-secret",
            github_webhook_secret="github-secret",
        )
        extra_httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=extra_httpd.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps(
                {
                    "action": "opened",
                    "issue": {"number": 7, "title": "GitHub task"},
                    "repository": {"full_name": "lusipad/ClawHarness"},
                }
            ).encode("utf-8")
            signature = "sha256=" + hmac.new(b"github-secret", body, hashlib.sha256).hexdigest()
            request = Request(
                f"http://127.0.0.1:{extra_httpd.server_address[1]}/webhooks/github",
                data=body,
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            request.add_header("X-GitHub-Event", "issues")
            request.add_header("X-GitHub-Delivery", "delivery-1")
            request.add_header("X-Hub-Signature-256", signature)
            with urlopen(request, timeout=5) as response:
                status = int(response.status)
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(202, status)
            self.assertEqual("task_dispatched", payload["action"])
            self.assertEqual("issues", bridge.github_calls[0]["event_type"])
            self.assertEqual("delivery-1", bridge.github_calls[0]["source_id"])
        finally:
            extra_httpd.shutdown()
            extra_httpd.server_close()
            thread.join(timeout=5)

    def test_github_webhook_rejects_invalid_signature(self) -> None:
        bridge = DummyBridge(self.store)
        handler = create_handler(
            bridge,
            ingress_token="ingress-secret",
            github_webhook_secret="github-secret",
        )
        extra_httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=extra_httpd.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{extra_httpd.server_address[1]}/webhooks/github",
                data=json.dumps({"action": "opened"}).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            request.add_header("X-GitHub-Event", "issues")
            request.add_header("X-GitHub-Delivery", "delivery-2")
            request.add_header("X-Hub-Signature-256", "sha256=bad")
            with self.assertRaises(HTTPError) as ctx:
                urlopen(request, timeout=5)
            status = int(ctx.exception.code)
            payload = json.loads(ctx.exception.read().decode("utf-8"))
            ctx.exception.close()
            self.assertEqual(401, status)
            self.assertEqual("invalid_signature", payload["error"])
            self.assertEqual([], bridge.github_calls)
        finally:
            extra_httpd.shutdown()
            extra_httpd.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
