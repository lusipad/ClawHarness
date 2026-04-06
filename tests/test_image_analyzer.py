from __future__ import annotations

import json
import unittest

from harness_runtime.image_analyzer import ImageAnalysisError, OpenAIImageAnalyzer


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses: list[tuple[int, dict[str, str], bytes]] = []

    def queue_json(self, payload: dict[str, object]) -> None:
        self.responses.append((200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")))

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
            }
        )
        if not self.responses:
            return 200, {"Content-Type": "application/json"}, b"{}"
        return self.responses.pop(0)


class OpenAIImageAnalyzerTests(unittest.TestCase):
    def test_analyze_posts_responses_payload_with_image_input(self) -> None:
        transport = RecordingTransport()
        transport.queue_json(
            {
                "id": "resp-1",
                "output_text": "图片里出现了 500 错误弹窗，建议先检查后端接口和鉴权链路。",
            }
        )
        analyzer = OpenAIImageAnalyzer(
            api_key="sk-test",
            base_url="https://api.example.invalid/v1",
            model="gpt-5.4",
            transport=transport,
        )

        result = analyzer.analyze(
            context_text="用户反馈提交后页面报错",
            attachment={"title": "error-shot", "image_url": "https://example.invalid/error.png"},
            task_key="AB#1001",
        )

        self.assertEqual("gpt-5.4", result.model)
        self.assertEqual("resp-1", result.response_id)
        self.assertIn("500 错误弹窗", result.summary)
        call = transport.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertEqual("https://api.example.invalid/v1/responses", call["url"])
        payload = json.loads(call["body"].decode("utf-8"))
        self.assertEqual("gpt-5.4", payload["model"])
        self.assertEqual("input_image", payload["input"][0]["content"][1]["type"])
        self.assertEqual("https://example.invalid/error.png", payload["input"][0]["content"][1]["image_url"])

    def test_analyze_extracts_text_from_output_content_array(self) -> None:
        transport = RecordingTransport()
        transport.queue_json(
            {
                "id": "resp-2",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "截图显示权限提示覆盖了主操作区，建议先检查角色和 feature flag 配置。",
                            }
                        ],
                    }
                ],
            }
        )
        analyzer = OpenAIImageAnalyzer(
            api_key="sk-test",
            model="gpt-5.4",
            transport=transport,
        )

        result = analyzer.analyze(
            context_text="入口按钮消失",
            attachment={"image_url": "https://example.invalid/missing-button.png"},
            task_key="AB#1002",
        )

        self.assertEqual("resp-2", result.response_id)
        self.assertIn("权限提示覆盖了主操作区", result.summary)

    def test_analyze_requires_image_url(self) -> None:
        analyzer = OpenAIImageAnalyzer(
            api_key="sk-test",
            model="gpt-5.4",
            transport=RecordingTransport(),
        )

        with self.assertRaises(ImageAnalysisError):
            analyzer.analyze(
                context_text="没有可用图片链接",
                attachment={"name": "broken"},
                task_key="AB#1003",
            )
