from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib import request
from urllib.error import HTTPError, URLError


Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Mapping[str, str], bytes]]


class ImageAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageAnalysisResult:
    model: str
    summary: str
    response_id: str | None = None


class ImageAnalyzer(Protocol):
    def analyze(
        self,
        *,
        context_text: str,
        attachment: Mapping[str, Any],
        task_key: str | None = None,
    ) -> ImageAnalysisResult:
        ...


class OpenAIImageAnalyzer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_output_tokens: int = 400,
        transport: Transport | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.max_output_tokens = max_output_tokens
        self.transport = transport or self._default_transport

    def analyze(
        self,
        *,
        context_text: str,
        attachment: Mapping[str, Any],
        task_key: str | None = None,
    ) -> ImageAnalysisResult:
        image_url = self._extract_image_url(attachment)
        if not image_url:
            raise ImageAnalysisError("image attachment is missing a usable URL")

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._build_prompt(context_text=context_text, attachment=attachment, task_key=task_key),
                        },
                        {
                            "type": "input_image",
                            "image_url": image_url,
                        },
                    ],
                }
            ],
            "max_output_tokens": self.max_output_tokens,
        }

        response = self._post("/responses", payload)
        summary = self._extract_output_text(response).strip()
        if not summary:
            raise ImageAnalysisError("image analysis response did not include text output")
        return ImageAnalysisResult(
            model=self.model,
            summary=summary,
            response_id=self._coerce_str(response.get("id")),
        )

    def _build_prompt(
        self,
        *,
        context_text: str,
        attachment: Mapping[str, Any],
        task_key: str | None,
    ) -> str:
        attachment_name = self._coerce_str(
            attachment.get("title")
            or attachment.get("name")
            or attachment.get("filename")
        ) or "未命名图片"
        task_line = f"任务：{task_key}" if task_key else "任务：未绑定任务编号"
        return "\n".join(
            [
                "你是 ClawHarness 的图片问题分析器。",
                task_line,
                f"图片名：{attachment_name}",
                f"补充上下文：{context_text or '无'}",
                "",
                "请用中文输出 2 到 4 句，必须包含：",
                "1. 你在图片里观察到的关键信息或异常",
                "2. 这对当前任务可能意味着什么",
                "3. 建议的下一步排查或修复动作",
                "不要输出 Markdown 标题或项目符号。",
            ]
        )

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        status_code, _headers, content = self.transport(
            "POST",
            url,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json.dumps(payload).encode("utf-8"),
        )
        if status_code >= 400:
            raise ImageAnalysisError(
                f"image analysis request failed with status {status_code}: {content.decode('utf-8', errors='replace')}"
            )
        if not content:
            raise ImageAnalysisError("image analysis request returned an empty response")
        try:
            return json.loads(content.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ImageAnalysisError("image analysis response was not valid JSON") from exc

    def _extract_output_text(self, payload: Mapping[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return output_text

        output = payload.get("output")
        if isinstance(output, list):
            chunks: list[str] = []
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for content_item in content:
                    if not isinstance(content_item, Mapping):
                        continue
                    text = content_item.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text.strip())
                    elif isinstance(text, Mapping):
                        value = text.get("value")
                        if isinstance(value, str) and value.strip():
                            chunks.append(value.strip())
            if chunks:
                return "\n".join(chunks)

        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                message = choice.get("message")
                if not isinstance(message, Mapping):
                    continue
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    chunks = []
                    for item in content:
                        if isinstance(item, Mapping):
                            text = item.get("text")
                            if isinstance(text, str) and text.strip():
                                chunks.append(text.strip())
                    if chunks:
                        return "\n".join(chunks)
        return ""

    def _extract_image_url(self, attachment: Mapping[str, Any]) -> str | None:
        for key in ("image_url", "imageUrl", "url", "downloadUrl", "download_url"):
            value = attachment.get(key)
            text = self._coerce_str(value)
            if text:
                return text
        return None

    def _coerce_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

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
            raise ImageAnalysisError(f"image analysis transport failed: {exc}") from exc
