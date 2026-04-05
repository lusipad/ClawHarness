from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .bridge import HarnessBridge


def create_handler(bridge: HarnessBridge, *, ingress_token: str | None):
    class HarnessHandler(BaseHTTPRequestHandler):
        server_version = "ClawHarnessBridge/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._write_json(HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path == "/readyz":
                self._write_json(HTTPStatus.OK, {"status": "ready"})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/webhooks/azure-devops":
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if ingress_token and not self._is_authorized(ingress_token):
                self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return

            payload = self._read_json_body()
            if payload is None:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return

            event_type = (
                self.headers.get("X-Ado-Event-Type")
                or self.headers.get("X-VSS-Event")
                or payload.get("eventType")
                or payload.get("event_type")
            )
            if not isinstance(event_type, str) or not event_type:
                query_event = parse_qs(parsed.query).get("event_type", [None])[0]
                event_type = query_event

            if not isinstance(event_type, str) or not event_type:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "missing_event_type"})
                return

            source_id = self.headers.get("X-Ado-Delivery-Id") or self.headers.get("X-VSS-Subscription-Id")
            result = bridge.handle_ado_event(event_type=event_type, payload=payload, source_id=source_id)
            status = HTTPStatus.ACCEPTED if result.accepted else HTTPStatus.OK
            self._write_json(
                status,
                {
                    "accepted": result.accepted,
                    "action": result.action,
                    "run_id": result.run_id,
                    "reason": result.reason,
                    "session_key": result.session_key,
                },
            )

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _is_authorized(self, token: str) -> bool:
            auth_header = self.headers.get("Authorization")
            if auth_header == f"Bearer {token}":
                return True
            if self.headers.get("x-harness-token") == token:
                return True
            return False

        def _read_json_body(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            try:
                raw = self.rfile.read(length)
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return HarnessHandler


def serve(bridge: HarnessBridge, *, host: str, port: int, ingress_token: str | None) -> ThreadingHTTPServer:
    handler = create_handler(bridge, ingress_token=ingress_token)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.serve_forever()
    return httpd
