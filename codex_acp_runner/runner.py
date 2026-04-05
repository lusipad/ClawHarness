from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


SpawnSession = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class ExecutorRequest:
    workspace_path: str
    task_prompt: str
    constraints: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    label: str | None = None
    mode: str = "run"
    thread: bool = False
    agent_id: str = "codex"
    stream_to_parent: bool = False

    def validate(self) -> None:
        if not Path(self.workspace_path).is_absolute():
            raise ValueError("workspace_path must be absolute")
        if self.mode not in {"run", "session"}:
            raise ValueError(f"Unsupported mode: {self.mode}")
        if self.mode == "session" and not self.thread:
            raise ValueError('mode="session" requires thread=True for ACP sessions')
        if not self.task_prompt.strip():
            raise ValueError("task_prompt must not be empty")


@dataclass(frozen=True)
class AcpSpawnResult:
    accepted: bool
    child_session_key: str | None
    session_id: str | None
    stream_log_path: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutorResult:
    status: str
    summary: str
    changed_files: list[str]
    checks: list[dict[str, Any]]
    follow_up: list[str]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExecutorResult":
        return cls(
            status=str(payload.get("status", "")),
            summary=str(payload.get("summary", "")),
            changed_files=[str(item) for item in payload.get("changed_files", [])],
            checks=[dict(item) for item in payload.get("checks", [])],
            follow_up=[str(item) for item in payload.get("follow_up", [])],
        )


class ExecutorRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutorRunOutcome:
    spawn: AcpSpawnResult
    result: ExecutorResult


class CodexAcpRunner:
    def __init__(self, spawn_session: SpawnSession):
        self.spawn_session = spawn_session

    def build_task_prompt(self, request: ExecutorRequest) -> str:
        request.validate()
        sections = [
            request.task_prompt.strip(),
            "",
            "Constraints:",
        ]
        if request.constraints:
            sections.extend(f"- {constraint}" for constraint in request.constraints)
        else:
            sections.append("- none")

        sections.extend(
            [
                "",
                "Artifacts:",
                "```json",
                json.dumps(request.artifacts, indent=2, sort_keys=True),
                "```",
            ]
        )
        result_path = request.artifacts.get("result_path")
        if isinstance(result_path, str) and result_path:
            sections.extend(
                [
                    "",
                    "Execution contract:",
                    f"- Write a JSON result artifact to `{result_path}`.",
                    '- Required keys: "status", "summary", "changed_files", "checks", "follow_up".',
                    "- Use absolute or workspace-relative changed file paths.",
                ]
            )
        return "\n".join(sections)

    def build_spawn_payload(self, request: ExecutorRequest, *, resume_session_id: str | None = None) -> dict[str, Any]:
        prompt = self.build_task_prompt(request)
        payload: dict[str, Any] = {
            "task": prompt,
            "runtime": "acp",
            "agentId": request.agent_id,
            "mode": request.mode,
            "cwd": request.workspace_path,
        }
        if request.thread:
            payload["thread"] = True
        if request.label:
            payload["label"] = request.label
        if request.stream_to_parent:
            payload["streamTo"] = "parent"
        if resume_session_id:
            payload["resumeSessionId"] = resume_session_id
        return payload

    def start(self, request: ExecutorRequest) -> AcpSpawnResult:
        payload = self.build_spawn_payload(request)
        response = self.spawn_session(payload)
        return self._to_spawn_result(response)

    def resume(self, request: ExecutorRequest, *, resume_session_id: str) -> AcpSpawnResult:
        payload = self.build_spawn_payload(request, resume_session_id=resume_session_id)
        response = self.spawn_session(payload)
        return self._to_spawn_result(response)

    def load_result(self, result_path: str | Path) -> ExecutorResult:
        path = Path(result_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ExecutorRunError(f"Failed to read executor result: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ExecutorRunError(f"Failed to parse executor result JSON: {path}") from exc
        return ExecutorResult.from_mapping(payload)

    def wait_for_result(
        self,
        result_path: str | Path,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 1.0,
    ) -> ExecutorResult:
        path = Path(result_path)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if path.exists():
                return self.load_result(path)
            time.sleep(poll_interval_seconds)
        raise ExecutorRunError(f"Timed out waiting for executor result: {path}")

    def run_and_wait(
        self,
        request: ExecutorRequest,
        *,
        result_path: str | Path,
        timeout_seconds: float,
        poll_interval_seconds: float = 1.0,
        resume_session_id: str | None = None,
    ) -> ExecutorRunOutcome:
        spawn = (
            self.resume(request, resume_session_id=resume_session_id)
            if resume_session_id
            else self.start(request)
        )
        if not spawn.accepted:
            raise ExecutorRunError(spawn.error or "ACP session spawn was not accepted")
        inline_result = spawn.raw.get("result")
        if isinstance(inline_result, Mapping):
            return ExecutorRunOutcome(spawn=spawn, result=ExecutorResult.from_mapping(inline_result))
        result = self.wait_for_result(
            result_path,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        return ExecutorRunOutcome(spawn=spawn, result=result)

    def _to_spawn_result(self, payload: Mapping[str, Any]) -> AcpSpawnResult:
        raw = dict(payload)
        details = raw.get("details")
        if isinstance(details, Mapping):
            raw = {**raw, **details}
        accepted = raw.get("accepted")
        if accepted is None and raw.get("status") is not None:
            accepted = str(raw.get("status")).lower() == "accepted"
        session_id = self._coerce_str(raw.get("sessionId")) or self._coerce_str(raw.get("childSessionKey"))
        return AcpSpawnResult(
            accepted=bool(accepted),
            child_session_key=self._coerce_str(raw.get("childSessionKey")),
            session_id=session_id,
            stream_log_path=self._coerce_str(raw.get("streamLogPath")),
            error=self._coerce_str(raw.get("error")),
            raw=raw,
        )

    def _coerce_str(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def dump_request(self, request: ExecutorRequest) -> dict[str, Any]:
        return asdict(request)
