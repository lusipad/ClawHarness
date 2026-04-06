from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from harness_runtime.server import create_handler
from run_store import RunStore, TaskRun


class DummyBridge:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def handle_ado_event(self, *, event_type: str, payload, source_id=None):
        raise AssertionError("POST webhook path should not be used in API tests")


class RuntimeServerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "harness.db"
        self.store = RunStore(self.db_path)
        self.store.initialize()
        run = self.store.create_run(
            TaskRun(
                run_id="run-1",
                provider_type="azure-devops",
                task_id="123",
                task_key="AI-Review-Test#123",
                session_id="hook:harness",
                executor_type="codex-cli",
                status="awaiting_review",
                repo_id="repo-1",
                branch_name="refs/heads/ai/ado/123",
                pr_id="21",
                started_at="2026-04-05T12:00:00Z",
                updated_at="2026-04-05T12:00:30Z",
            )
        )
        self.store.append_audit(
            run.run_id,
            "branch_pushed",
            payload={"branch_name": run.branch_name, "pr_id": run.pr_id},
            created_at="2026-04-05T12:00:31Z",
        )
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(DummyBridge(self.store), ingress_token="secret"))
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _request_json(self, path: str, *, token: str | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(f"{self.base_url}{path}")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)

    def test_api_requires_token(self) -> None:
        request = urllib.request.Request(f"{self.base_url}/api/summary")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(401, ctx.exception.code)
        ctx.exception.close()

    def test_list_runs_returns_serialized_runs(self) -> None:
        status, payload = self._request_json("/api/runs?limit=10", token="secret")
        self.assertEqual(200, status)
        self.assertEqual(1, payload["count"])
        self.assertEqual("run-1", payload["runs"][0]["run_id"])
        self.assertEqual("awaiting_review", payload["runs"][0]["status"])

    def test_get_run_and_audit_returns_parsed_payloads(self) -> None:
        run_status, run_payload = self._request_json("/api/runs/run-1", token="secret")
        audit_status, audit_payload = self._request_json("/api/runs/run-1/audit", token="secret")
        self.assertEqual(200, run_status)
        self.assertEqual(200, audit_status)
        self.assertEqual("21", run_payload["run"]["pr_id"])
        self.assertEqual("branch_pushed", audit_payload["audit"][0]["event_type"])
        self.assertEqual("21", audit_payload["audit"][0]["payload"]["pr_id"])

    def test_summary_returns_status_counts(self) -> None:
        status, payload = self._request_json("/api/summary", token="secret")
        self.assertEqual(200, status)
        self.assertEqual(1, payload["total_runs"])
        self.assertEqual(1, payload["active_runs"])
        self.assertEqual(1, payload["status_counts"]["awaiting_review"])

    def test_readonly_token_authorizes_api_when_different_from_ingress_token(self) -> None:
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(
                DummyBridge(self.store),
                ingress_token="ingress-secret",
                readonly_token="readonly-secret",
            ),
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            request = urllib.request.Request(f"{base_url}/api/summary")
            request.add_header("Authorization", "Bearer readonly-secret")
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(1, payload["total_runs"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
