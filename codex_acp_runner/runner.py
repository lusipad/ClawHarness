from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping


SpawnSession = Callable[[dict[str, Any]], Mapping[str, Any]]
CliShellRunner = Callable[
    [list[str], str | Path | None, Mapping[str, str] | None, float | None, str | None],
    subprocess.CompletedProcess[str],
]


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
            checks=_normalize_checks_payload(payload.get("checks")),
            follow_up=[str(item) for item in payload.get("follow_up", [])],
        )


class ExecutorRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutorRunOutcome:
    spawn: AcpSpawnResult
    result: ExecutorResult


def _normalize_check_item(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    return {
        "name": str(item),
        "status": "informational",
    }


def _normalize_checks_payload(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_normalize_check_item(item) for item in value]


def _build_task_prompt(request: ExecutorRequest) -> str:
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
                "- Whether or not the file write succeeds, your final response must be the same JSON object and nothing else.",
            ]
        )
    return "\n".join(sections)


def _load_result(result_path: str | Path) -> ExecutorResult:
    path = Path(result_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExecutorRunError(f"Failed to read executor result: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExecutorRunError(f"Failed to parse executor result JSON: {path}") from exc
    return ExecutorResult.from_mapping(payload)


class CodexAcpRunner:
    def __init__(self, spawn_session: SpawnSession):
        self.spawn_session = spawn_session

    def build_task_prompt(self, request: ExecutorRequest) -> str:
        return _build_task_prompt(request)

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
        return _load_result(result_path)

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


class CodexCliRunner:
    def __init__(
        self,
        *,
        codex_command: str = "codex",
        shell_runner: CliShellRunner | None = None,
    ):
        self.codex_command = self._resolve_codex_command(codex_command)
        self.shell_runner = shell_runner or self._default_shell_runner

    def build_task_prompt(self, request: ExecutorRequest) -> str:
        return _build_task_prompt(request)

    def build_exec_command(self, request: ExecutorRequest, *, result_path: str | Path) -> list[str]:
        last_message_path = str(Path(result_path).with_suffix(".last-message.txt"))
        return [
            self.codex_command,
            "exec",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "--color",
            "never",
            "--cd",
            request.workspace_path,
            "--output-last-message",
            last_message_path,
            "-",
        ]

    def run_and_wait(
        self,
        request: ExecutorRequest,
        *,
        result_path: str | Path,
        timeout_seconds: float,
        poll_interval_seconds: float = 1.0,
        resume_session_id: str | None = None,
    ) -> ExecutorRunOutcome:
        del poll_interval_seconds
        request.validate()
        command = self.build_exec_command(request, result_path=result_path)
        prompt = self.build_task_prompt(request)
        completed = self.shell_runner(
            command,
            request.workspace_path,
            {"GIT_TERMINAL_PROMPT": "0"},
            timeout_seconds,
            prompt,
        )
        result_file = Path(result_path)
        if result_file.exists():
            return ExecutorRunOutcome(
                spawn=AcpSpawnResult(
                    accepted=True,
                    child_session_key=None,
                    session_id=resume_session_id or f"codex-cli:{int(time.time())}",
                    raw={"command": command, "exit_code": completed.returncode},
                ),
                result=_load_result(result_file),
            )
        recovered = self._recover_result_from_last_message(request, result_file)
        if recovered is not None:
            return ExecutorRunOutcome(
                spawn=AcpSpawnResult(
                    accepted=True,
                    child_session_key=None,
                    session_id=resume_session_id or f"codex-cli:{int(time.time())}",
                    raw={
                        "command": command,
                        "exit_code": completed.returncode,
                        "recovered_from_last_message": True,
                    },
                ),
                result=recovered,
            )

        if completed.returncode != 0:
            raise ExecutorRunError(self._format_failure(command, completed))
        raise ExecutorRunError(f"Codex exec completed without writing result artifact: {result_file}")

    def _format_failure(self, command: list[str], completed: subprocess.CompletedProcess[str]) -> str:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        excerpt = stderr or stdout or "unknown error"
        if len(excerpt) > 2000:
            excerpt = excerpt[:2000] + "...<truncated>"
        return f"Codex exec failed ({completed.returncode}): {' '.join(command)} | {excerpt}"

    def _resolve_codex_command(self, codex_command: str) -> str:
        if os.name != "nt":
            return codex_command
        if Path(codex_command).suffix or any(sep in codex_command for sep in ("/", "\\")):
            return codex_command
        for candidate in ("codex.cmd", "codex.exe", "codex.bat", codex_command):
            if shutil.which(candidate):
                return candidate
        return codex_command

    def _recover_result_from_last_message(
        self,
        request: ExecutorRequest,
        result_path: Path,
    ) -> ExecutorResult | None:
        last_message_path = result_path.with_suffix(".last-message.txt")
        try:
            raw_message = last_message_path.read_text(encoding="utf-8")
        except OSError:
            return None
        message = raw_message.strip()
        if not message:
            return None

        default_changed_files = self._collect_changed_files(request.workspace_path)
        default_follow_up = self._extract_follow_up(message)
        payload = self._extract_json_payload(message)
        if payload is None:
            payload = {
                "status": self._infer_status_from_last_message(message),
                "summary": self._summarize_last_message(message),
                "changed_files": default_changed_files,
                "checks": [],
                "follow_up": default_follow_up,
            }
        else:
            payload = self._normalize_result_payload(
                payload,
                default_status=self._infer_status_from_last_message(message),
                default_summary=self._summarize_last_message(message),
                default_changed_files=default_changed_files,
                default_follow_up=default_follow_up,
            )

        result_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return ExecutorResult.from_mapping(payload)

    def _normalize_result_payload(
        self,
        payload: Mapping[str, Any],
        *,
        default_status: str,
        default_summary: str,
        default_changed_files: list[str],
        default_follow_up: list[str],
    ) -> dict[str, Any]:
        changed_files = payload.get("changed_files")
        checks = payload.get("checks")
        follow_up = payload.get("follow_up")
        normalized_follow_up = (
            [str(item) for item in follow_up]
            if isinstance(follow_up, list)
            else list(default_follow_up)
        )
        return {
            "status": str(payload.get("status") or default_status),
            "summary": str(payload.get("summary") or default_summary),
            "changed_files": (
                [str(item) for item in changed_files]
                if isinstance(changed_files, list)
                else list(default_changed_files)
            ),
            "checks": _normalize_checks_payload(checks),
            "follow_up": normalized_follow_up,
        }

    def _extract_json_payload(self, message: str) -> Mapping[str, Any] | None:
        for candidate in self._json_candidates(message):
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                return payload
        return None

    def _json_candidates(self, message: str) -> list[str]:
        candidates: list[str] = []
        stripped = message.strip()
        if stripped:
            candidates.append(stripped)
        if "```" in message:
            parts = message.split("```")
            for index in range(1, len(parts), 2):
                part = parts[index].strip()
                if not part:
                    continue
                if "\n" in part:
                    header, remainder = part.split("\n", 1)
                    if header.strip().lower() == "json":
                        part = remainder.strip()
                candidates.append(part)
        brace_match = re.search(r"\{[\s\S]*\}", message)
        if brace_match:
            candidates.append(brace_match.group(0).strip())
        return candidates

    def _collect_changed_files(self, workspace_path: str) -> list[str]:
        try:
            completed = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if completed.returncode != 0:
            return []

        changed_files: list[str] = []
        for raw_line in completed.stdout.splitlines():
            line = raw_line.rstrip()
            if len(line) < 4:
                continue
            path_text = line[3:].strip()
            if " -> " in path_text:
                path_text = path_text.split(" -> ", 1)[1].strip()
            normalized = path_text.replace("\\", "/")
            if normalized and normalized not in changed_files:
                changed_files.append(normalized)
        return changed_files

    def _extract_follow_up(self, message: str) -> list[str]:
        headings = {"follow-up", "follow up", "next steps", "next step", "next actions", "remaining work"}
        follow_up: list[str] = []
        capture = False
        for raw_line in message.splitlines():
            line = raw_line.strip()
            normalized = line.rstrip(":").strip().lower()
            if normalized in headings:
                capture = True
                continue
            if not capture:
                continue
            if not line:
                if follow_up:
                    break
                continue
            item = re.sub(r"^(?:[-*]|\d+[.)])\s*", "", line).strip()
            if not item:
                if follow_up:
                    break
                continue
            follow_up.append(item)
        return follow_up

    def _infer_status_from_last_message(self, message: str) -> str:
        explicit_status = re.search(
            r'(?im)^\s*(?:status|result status)\s*[:=]\s*"?(completed|planned|success|needs_human|approved|passed|ready)"?\s*$',
            message,
        )
        if explicit_status:
            return explicit_status.group(1).lower()
        normalized = message.lower()
        blocked_signals = (
            "needs_human",
            "needs human",
            "need human",
            "awaiting_human",
            "awaiting human",
            "requires human",
            "manual intervention",
            "cannot proceed",
            "can't proceed",
            "not safe",
            "too risky",
            "blocked",
        )
        if any(token in normalized for token in blocked_signals):
            return "needs_human"
        return "completed"

    def _summarize_last_message(self, message: str) -> str:
        summary = message.strip()
        if len(summary) > 4000:
            return summary[:4000] + "...<truncated>"
        return summary

    def _default_shell_runner(
        self,
        command: list[str],
        cwd: str | Path | None,
        env_overrides: Mapping[str, str] | None,
        timeout_seconds: float | None,
        input_text: str | None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(**env_overrides) if env_overrides else None
        merged_env = None
        if env is not None:
            merged_env = dict(**env)
            merged_env = {**merged_env}
        base_env = None
        if merged_env is not None:
            base_env = os.environ.copy()
            base_env.update(merged_env)
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=base_env,
            capture_output=True,
            text=True,
            input=input_text,
            check=False,
            timeout=timeout_seconds,
        )
