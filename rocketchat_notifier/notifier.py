from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping
from urllib import request
from urllib.error import HTTPError, URLError


Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Mapping[str, str], bytes]]

_EVENT_COLORS = {
    "task_started": "#1d74f5",
    "pr_opened": "#2eb67d",
    "ci_failed": "#d64541",
    "task_blocked": "#f2c94c",
    "task_completed": "#2eb67d",
}


@dataclass(frozen=True)
class NotificationMessage:
    text: str
    channel: str | None = None
    alias: str | None = None
    emoji: str | None = None
    parse_urls: bool = False
    attachments: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "text": self.text,
            "parseUrls": self.parse_urls,
        }
        if self.channel:
            payload["channel"] = self.channel
        if self.alias:
            payload["alias"] = self.alias
        if self.emoji:
            payload["emoji"] = self.emoji
        if self.attachments:
            payload["attachments"] = self.attachments
        return payload


class RocketChatNotifierError(RuntimeError):
    pass


class RocketChatNotifier:
    def __init__(
        self,
        *,
        webhook_url: str,
        default_channel: str | None = None,
        alias: str = "ClawHarness",
        emoji: str = ":robot_face:",
        transport: Transport | None = None,
    ):
        self.webhook_url = webhook_url
        self.default_channel = default_channel
        self.alias = alias
        self.emoji = emoji
        self.transport = transport or self._default_transport

    def build_lifecycle_message(
        self,
        *,
        event_type: str,
        task_key: str,
        run_id: str,
        summary: str,
        details: dict[str, Any] | None = None,
        channel: str | None = None,
    ) -> NotificationMessage:
        color = _EVENT_COLORS.get(event_type, "#4a4a4a")
        attachments = [
            {
                "color": color,
                "title": event_type.replace("_", " ").title(),
                "fields": self._build_fields(task_key=task_key, run_id=run_id, details=details or {}),
            }
        ]
        return NotificationMessage(
            text=summary,
            channel=channel or self.default_channel,
            alias=self.alias,
            emoji=self.emoji,
            parse_urls=False,
            attachments=attachments,
        )

    def post_message(self, message: NotificationMessage) -> dict[str, Any]:
        payload = message.to_payload()
        status_code, _headers, content = self.transport(
            "POST",
            self.webhook_url,
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json.dumps(payload).encode("utf-8"),
        )
        if status_code >= 400:
            raise RocketChatNotifierError(
                f"Rocket.Chat webhook failed with status {status_code}: {content.decode('utf-8', errors='replace')}"
            )
        if not content:
            return {}
        return json.loads(content.decode("utf-8"))

    def notify_lifecycle(
        self,
        *,
        event_type: str,
        task_key: str,
        run_id: str,
        summary: str,
        details: dict[str, Any] | None = None,
        channel: str | None = None,
    ) -> dict[str, Any]:
        message = self.build_lifecycle_message(
            event_type=event_type,
            task_key=task_key,
            run_id=run_id,
            summary=summary,
            details=details,
            channel=channel,
        )
        return self.post_message(message)

    def _build_fields(self, *, task_key: str, run_id: str, details: dict[str, Any]) -> list[dict[str, Any]]:
        fields = [
            {"title": "Task", "value": task_key, "short": True},
            {"title": "Run", "value": run_id, "short": True},
        ]
        for key, value in details.items():
            fields.append({"title": key.replace("_", " ").title(), "value": str(value), "short": False})
        return fields

    def _default_transport(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> tuple[int, Mapping[str, str], bytes]:
        req = request.Request(url=url, data=body, method=method, headers=headers)
        try:
            with request.urlopen(req) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()
        except URLError as exc:
            raise RocketChatNotifierError(f"Rocket.Chat transport failed: {exc}") from exc
