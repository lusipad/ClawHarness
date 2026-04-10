from __future__ import annotations

import hashlib
import hmac
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from run_store import VALID_STATUSES

from .bridge import HarnessBridge


def create_handler(
    bridge: HarnessBridge,
    *,
    ingress_token: str | None,
    readonly_token: str | None = None,
    control_token: str | None = None,
    chat_command_token: str | None = None,
    github_webhook_secret: str | None = None,
):
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
            if parsed.path.startswith("/api/"):
                api_tokens = [token for token in (readonly_token, control_token, ingress_token) if token]
                if api_tokens and not self._is_authorized_any(api_tokens):
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                self._handle_api_get(parsed)
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                api_token = control_token or ingress_token
                if api_token and not self._is_authorized(api_token):
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                self._handle_api_post(parsed)
                return
            if parsed.path == "/webhooks/chat/rocketchat":
                raw = self._read_body()
                if raw is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_body"})
                    return
                payload = self._load_structured_bytes(raw)
                if payload is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_body"})
                    return
                expected_token = chat_command_token or ingress_token
                if expected_token and str(payload.get("token") or "").strip() != expected_token:
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                result = bridge.handle_chat_command(provider_type="rocketchat", payload=payload)
                self._write_json(HTTPStatus.OK, result.to_payload())
                return
            if parsed.path == "/webhooks/chat/weixin":
                raw = self._read_body()
                if raw is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_body"})
                    return
                payload = self._load_structured_bytes(raw)
                if payload is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_body"})
                    return
                expected_token = chat_command_token or ingress_token
                if expected_token and str(payload.get("token") or "").strip() != expected_token:
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                result = bridge.handle_chat_command(provider_type="weixin", payload=payload)
                self._write_json(HTTPStatus.OK, result.to_payload())
                return
            if parsed.path == "/webhooks/github":
                raw = self._read_body()
                if raw is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_body"})
                    return
                if github_webhook_secret:
                    if not self._is_valid_github_signature(raw, github_webhook_secret):
                        self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_signature"})
                        return
                elif ingress_token and not self._is_authorized(ingress_token):
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return

                payload = self._load_json_bytes(raw)
                if payload is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return

                event_type = self.headers.get("X-GitHub-Event")
                if not isinstance(event_type, str) or not event_type:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "missing_event_type"})
                    return

                source_id = self.headers.get("X-GitHub-Delivery")
                result = bridge.handle_github_event(event_type=event_type, payload=payload, source_id=source_id)
                self._write_bridge_result(result)
                return
            if parsed.path != "/webhooks/azure-devops":
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if ingress_token and not self._is_authorized(ingress_token):
                self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return

            raw = self._read_body()
            if raw is None:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return
            payload = self._load_json_bytes(raw)
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
            self._write_bridge_result(result)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _handle_api_get(self, parsed) -> None:
            if parsed.path == "/api/summary":
                self._write_json(HTTPStatus.OK, bridge.store.summarize_runs())
                return
            if parsed.path == "/api/runs":
                query = parse_qs(parsed.query)
                status = query.get("status", [None])[0]
                if status is not None and status not in VALID_STATUSES:
                    self._write_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_status", "valid_statuses": list(VALID_STATUSES)},
                    )
                    return
                task_key = query.get("task_key", [None])[0]
                limit_raw = query.get("limit", ["50"])[0]
                try:
                    limit = int(limit_raw)
                except ValueError:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_limit"})
                    return
                runs = bridge.store.list_runs(status=status, task_key=task_key, limit=limit)
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "summary": bridge.store.summarize_runs(),
                        "runs": [self._serialize_run(run) for run in runs],
                        "count": len(runs),
                        "filters": {
                            "status": status,
                            "task_key": task_key,
                            "limit": max(1, min(limit, 500)),
                        },
                    },
                )
                return

            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "runs":
                run = bridge.store.get_run(parts[2])
                if run is None:
                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                    return
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "run": self._serialize_run(run),
                        "audit_count": len(bridge.store.list_audit(parts[2])),
                    },
                )
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "runs" and parts[3] == "graph":
                run = bridge.store.get_run(parts[2])
                if run is None:
                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                    return
                parent_link = bridge.store.get_parent_relationship(parts[2])
                child_links = bridge.store.list_child_relationships(parts[2])
                checkpoints = bridge.store.list_checkpoints(parts[2])
                artifacts = bridge.store.list_artifacts(parts[2])
                skill_selections = bridge.store.list_skill_selections(parts[2])
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "run": self._serialize_run(run),
                        "parent_run": self._serialize_run(parent_link["run"]) if parent_link is not None else None,
                        "parent_relation": self._serialize_relation(parent_link) if parent_link is not None else None,
                        "child_runs": [self._serialize_child_relationship(link) for link in child_links],
                        "checkpoints": [self._serialize_store_payload(item) for item in checkpoints],
                        "artifacts": [self._serialize_store_payload(item) for item in artifacts],
                        "skill_selections": [self._serialize_store_payload(item) for item in skill_selections],
                    },
                )
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "runs" and parts[3] == "audit":
                run = bridge.store.get_run(parts[2])
                if run is None:
                    self._write_json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                    return
                audit = bridge.store.list_audit(parts[2])
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "run": self._serialize_run(run),
                        "run_id": parts[2],
                        "audit": [self._serialize_audit(entry) for entry in audit],
                        "count": len(audit),
                    },
                )
                return

            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def _handle_api_post(self, parsed) -> None:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "runs" and parts[3] == "command":
                raw = self._read_body()
                if raw is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return
                payload = self._load_json_bytes(raw)
                if payload is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return
                command_payload = dict(payload)
                command_payload.setdefault("run_id", parts[2])
                result = bridge.handle_chat_command(provider_type="bot-view", payload=command_payload)
                status = HTTPStatus.OK if result.ok else HTTPStatus.BAD_REQUEST
                self._write_json(
                    status,
                    {
                        "ok": result.ok,
                        "command": result.command,
                        "run_id": result.run_id,
                        "response_type": result.response_type,
                        "text": result.text,
                        "attachments": result.attachments,
                    },
                )
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def _is_authorized(self, token: str) -> bool:
            auth_header = self.headers.get("Authorization")
            if auth_header == f"Bearer {token}":
                return True
            if self.headers.get("x-harness-token") == token:
                return True
            return False

        def _is_authorized_any(self, tokens: list[str]) -> bool:
            return any(self._is_authorized(token) for token in tokens)

        def _read_body(self) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            return self.rfile.read(length)

        def _load_json_bytes(self, raw: bytes) -> dict[str, Any] | None:
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None

        def _load_structured_bytes(self, raw: bytes) -> dict[str, Any] | None:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type == "application/json":
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
            if content_type == "application/x-www-form-urlencoded":
                try:
                    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                except UnicodeDecodeError:
                    return None
                return {key: values[-1] if values else "" for key, values in parsed.items()}
            return None

        def _is_valid_github_signature(self, raw: bytes, secret: str) -> bool:
            signature = self.headers.get("X-Hub-Signature-256")
            if not isinstance(signature, str) or not signature.startswith("sha256="):
                return False
            expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature, expected)

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_bridge_result(self, result) -> None:
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

        def _serialize_run(self, run) -> dict[str, Any]:
            return {
                "run_id": run.run_id,
                "provider_type": run.provider_type,
                "task_id": run.task_id,
                "task_key": run.task_key,
                "repo_id": run.repo_id,
                "branch_name": run.branch_name,
                "workspace_path": run.workspace_path,
                "pr_id": run.pr_id,
                "ci_run_id": run.ci_run_id,
                "chat_thread_id": run.chat_thread_id,
                "session_id": run.session_id,
                "executor_type": run.executor_type,
                "status": run.status,
                "retry_count": run.retry_count,
                "started_at": run.started_at,
                "updated_at": run.updated_at,
                "last_error": run.last_error,
            }

        def _serialize_relation(self, relationship: dict[str, Any]) -> dict[str, Any]:
            relation_type = str(relationship["relation_type"])
            return {
                "relation_type": relation_type,
                "agent_role": self._agent_role_from_relation(relation_type),
                "created_at": relationship["created_at"],
            }

        def _serialize_child_relationship(self, relationship: dict[str, Any]) -> dict[str, Any]:
            run = relationship["run"]
            checkpoints = bridge.store.list_checkpoints(run.run_id)
            artifacts = bridge.store.list_artifacts(run.run_id)
            latest_checkpoint = checkpoints[-1] if checkpoints else None
            latest_conclusion = self._latest_executor_conclusion(artifacts)
            skill_selections = bridge.store.list_skill_selections(run.run_id)
            relation = self._serialize_relation(relationship)
            return {
                "run": self._serialize_run(run),
                **relation,
                "latest_checkpoint": self._serialize_store_payload(latest_checkpoint) if latest_checkpoint is not None else None,
                "latest_conclusion": latest_conclusion,
                "artifact_count": len(artifacts),
                "checkpoint_count": len(checkpoints),
                "skill_selections": [self._serialize_store_payload(item) for item in skill_selections],
            }

        def _serialize_audit(self, entry: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": entry["id"],
                "run_id": entry["run_id"],
                "event_type": entry["event_type"],
                "payload": self._parse_payload_json(entry.get("payload_json")),
                "created_at": entry["created_at"],
            }

        def _serialize_store_payload(self, entry: dict[str, Any]) -> dict[str, Any]:
            result = dict(entry)
            result["payload"] = self._parse_payload_json(entry.get("payload_json"))
            result.pop("payload_json", None)
            return result

        def _latest_executor_conclusion(self, artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
            for artifact in reversed(artifacts):
                if artifact.get("artifact_type") != "executor-result":
                    continue
                return {
                    "artifact_name": artifact.get("artifact_name"),
                    "created_at": artifact.get("created_at"),
                    "payload": self._parse_payload_json(artifact.get("payload_json")),
                }
            return None

        def _agent_role_from_relation(self, relation_type: str) -> str | None:
            if relation_type.startswith("agent-"):
                suffix = relation_type.removeprefix("agent-").strip()
                return suffix or None
            return None

        def _parse_payload_json(self, payload: Any) -> Any:
            if not isinstance(payload, str) or not payload:
                return None
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return payload

    return HarnessHandler


def serve(
    bridge: HarnessBridge,
    *,
    host: str,
    port: int,
    ingress_token: str | None,
    readonly_token: str | None = None,
    control_token: str | None = None,
    chat_command_token: str | None = None,
    github_webhook_secret: str | None = None,
) -> ThreadingHTTPServer:
    handler = create_handler(
        bridge,
        ingress_token=ingress_token,
        readonly_token=readonly_token,
        control_token=control_token,
        chat_command_token=chat_command_token,
        github_webhook_secret=github_webhook_secret,
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.serve_forever()
    return httpd
