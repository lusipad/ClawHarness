from __future__ import annotations

import json
from typing import Any, Callable, Mapping
from urllib import request
from urllib.error import HTTPError, URLError


Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Mapping[str, str], bytes]]


class OpenClawWebhookError(RuntimeError):
    pass


class OpenClawWebhookClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        path: str = "/hooks",
        transport: Transport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.path = "/" + path.strip("/")
        self.transport = transport or self._default_transport

    def wake(self, text: str, *, mode: str = "now") -> dict[str, Any]:
        return self._post("wake", {"text": text, "mode": mode})

    def run_agent(
        self,
        *,
        message: str,
        name: str,
        agent_id: str,
        session_key: str,
        wake_mode: str = "now",
        deliver: bool = False,
        timeout_seconds: int = 120,
    ) -> dict[str, Any]:
        return self._post(
            "agent",
            {
                "message": message,
                "name": name,
                "agentId": agent_id,
                "sessionKey": session_key,
                "wakeMode": wake_mode,
                "deliver": deliver,
                "timeoutSeconds": timeout_seconds,
            },
        )

    def invoke_tool(
        self,
        *,
        tool: str,
        args: Mapping[str, Any],
        action: str | None = None,
        session_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool": tool,
            "args": dict(args),
        }
        if action:
            payload["action"] = action
        if session_key:
            payload["sessionKey"] = session_key
        response = self._post_absolute("/tools/invoke", payload)
        if response.get("ok") is False:
            raise OpenClawWebhookError(f"OpenClaw tool invoke failed: {response}")
        result = response.get("result")
        if isinstance(result, Mapping):
            return dict(result)
        if result is None:
            return {}
        return {"result": result}

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_absolute(f"{self.path}/{endpoint}", payload)

    def _post_absolute(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        status_code, _headers, content = self.transport(
            "POST",
            url,
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json.dumps(payload).encode("utf-8"),
        )
        if status_code >= 400:
            raise OpenClawWebhookError(
                f"OpenClaw webhook failed with status {status_code}: {content.decode('utf-8', errors='replace')}"
            )
        if not content:
            return {}
        return json.loads(content.decode("utf-8"))

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
            raise OpenClawWebhookError(f"OpenClaw webhook transport failed: {exc}") from exc
