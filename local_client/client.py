from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from workflow_provider import (
    CommitPushResult,
    NormalizedProviderEvent,
    ProviderApiError,
    RepositoryInfo,
    WorkspacePreparationResult,
)


ShellRunner = Callable[[list[str], str | Path | None, Mapping[str, str] | None], subprocess.CompletedProcess[str]]


class LocalTaskProviderError(ProviderApiError):
    pass


class LocalTaskClient:
    provider_type = "local-task"
    display_name = "Local Task"

    def __init__(
        self,
        *,
        repository_path: str | Path | None = None,
        task_directory: str | Path | None = None,
        review_directory: str | Path | None = None,
        base_branch: str | None = None,
        push_enabled: bool = False,
        shell_runner: ShellRunner | None = None,
    ):
        self.repository_path = Path(repository_path).resolve() if repository_path else None
        self.task_directory = Path(task_directory).resolve() if task_directory else None
        self.review_directory = Path(review_directory).resolve() if review_directory else None
        self.base_branch = self._normalize_branch_ref(base_branch) if base_branch else None
        self.push_enabled = push_enabled
        self.shell_runner = shell_runner or self._default_shell_runner

    def normalize_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> NormalizedProviderEvent:
        task_id = payload.get("task_id") or payload.get("id") or payload.get("taskId")
        repo_id = payload.get("repo_id") or payload.get("repository_id")
        repo_name = self._resolve_repository_path(repo_id).name if (repo_id or self.repository_path) else "local"
        task_key = payload.get("task_key") or (f"{repo_name}#{task_id}" if task_id is not None else None)
        normalized_type = event_type if event_type.startswith("task.") else f"task.{event_type}"
        actor = payload.get("actor") if isinstance(payload.get("actor"), Mapping) else {}
        return NormalizedProviderEvent(
            event_type=normalized_type,
            provider_type=self.provider_type,
            source_id=source_id,
            task_id=str(task_id) if task_id is not None else None,
            task_key=str(task_key) if task_key is not None else None,
            repo_id=str(repo_id) if repo_id is not None else (str(self.repository_path) if self.repository_path else None),
            pr_id=None,
            ci_run_id=None,
            chat_thread_id=None,
            actor=dict(actor),
            payload=dict(payload),
        )

    def get_task(
        self,
        task_id: int | str,
        *,
        repo_id: str | None = None,
        fields: list[str] | None = None,
        expand: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        del fields, expand, as_of
        repository = self._resolve_repository_path(repo_id)
        task_file = self._resolve_task_file(str(task_id))
        payload = self._load_task_payload(task_file)
        raw_fields = payload.get("fields") if isinstance(payload.get("fields"), Mapping) else {}
        task_fields = dict(raw_fields)
        task_fields.setdefault("System.TeamProject", repository.name)
        task_fields.setdefault("System.Title", self._task_title(task_file, payload))
        task_fields.setdefault("System.Description", self._task_description(task_file, payload))
        task_fields.setdefault("System.State", self._task_state(payload))
        task_fields["LocalTask.FilePath"] = str(task_file)
        task_fields["LocalTask.RepositoryPath"] = str(repository)
        return {
            "id": str(task_id),
            "path": str(task_file),
            "repository": str(repository),
            "fields": task_fields,
        }

    def add_task_comment(
        self,
        task_id: int | str,
        text: str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        del repo_id
        comments_path = self._review_root() / "task-comments" / f"{self._safe_name(str(task_id))}.jsonl"
        comments_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "id": uuid.uuid4().hex[:8],
            "task_id": str(task_id),
            "text": text,
            "created_at": self._utc_now(),
        }
        with comments_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"id": entry["id"], "path": str(comments_path), "text": text}

    def complete_task(
        self,
        task_id: int | str,
        *,
        repo_id: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        del repo_id
        state_path = self._review_root() / "task-state" / f"{self._safe_name(str(task_id))}.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": str(task_id),
            "state": "completed",
            "updated_at": self._utc_now(),
        }
        if comment:
            payload["comment"] = comment
            self.add_task_comment(task_id, comment)
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"id": str(task_id), "state": "completed", "path": str(state_path)}

    def get_repository(self, repository_id: str | None = None) -> RepositoryInfo:
        repo_path = self._resolve_repository_path(repository_id)
        default_branch = self.base_branch or self._detect_default_branch(repo_path)
        return RepositoryInfo(
            repository_id=str(repo_path),
            name=repo_path.name,
            default_branch=default_branch,
            remote_url=str(repo_path),
            web_url=None,
        )

    def prepare_workspace(
        self,
        repository_id: str,
        *,
        workspace_root: str | Path,
        run_id: str,
    ) -> WorkspacePreparationResult:
        repository = self.get_repository(repository_id)
        root = Path(workspace_root)
        workspace_path = root / self._workspace_name(repository.name, run_id)
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        if workspace_path.exists():
            raise LocalTaskProviderError(f"Workspace already exists for run {run_id}: {workspace_path}")
        clone_command = [
            "git",
            "clone",
            "--origin",
            "origin",
            "--branch",
            self._branch_short_name(repository.default_branch),
            repository.remote_url,
            str(workspace_path),
        ]
        self._run_git(clone_command, cwd=root)
        return WorkspacePreparationResult(
            repository=repository,
            workspace_path=str(workspace_path),
            base_branch=repository.default_branch,
        )

    def create_branch(
        self,
        workspace_path: str | Path,
        *,
        branch_name: str,
        base_branch: str,
    ) -> str:
        workspace = Path(workspace_path)
        base_ref = self._normalize_branch_ref(base_branch)
        branch_ref = self._normalize_branch_ref(branch_name)
        branch_short = self._branch_short_name(branch_ref)
        base_short = self._branch_short_name(base_ref)
        self._run_git(["git", "fetch", "origin", base_ref], cwd=workspace)
        self._run_git(["git", "checkout", "-B", branch_short, f"origin/{base_short}"], cwd=workspace)
        return branch_ref

    def commit_and_push(
        self,
        workspace_path: str | Path,
        *,
        branch_name: str,
        commit_message: str,
        author_name: str = "ClawHarness",
        author_email: str = "clawharness@local.invalid",
        allow_empty: bool = False,
    ) -> CommitPushResult:
        workspace = Path(workspace_path)
        branch_ref = self._normalize_branch_ref(branch_name)

        status = self._run_git(["git", "status", "--short"], cwd=workspace)
        created_commit = bool(status.stdout.strip())
        if not created_commit and not allow_empty:
            raise LocalTaskProviderError(f"No changes to commit in workspace {workspace}")

        self._run_git(["git", "add", "-A"], cwd=workspace)
        commit_command = [
            "git",
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-m",
            commit_message,
        ]
        if allow_empty:
            commit_command.append("--allow-empty")
        self._run_git(commit_command, cwd=workspace)
        commit_sha = self._run_git(["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
        if self.push_enabled:
            self._run_git(["git", "push", "-u", "origin", f"HEAD:{branch_ref}"], cwd=workspace)
        return CommitPushResult(
            branch_name=branch_ref,
            commit_sha=commit_sha,
            remote_ref=branch_ref,
            created_commit=created_commit,
        )

    def create_pull_request(
        self,
        repository_id: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[dict[str, Any]] | None = None,
        supports_iterations: bool | None = None,
    ) -> dict[str, Any]:
        del reviewers, supports_iterations
        review_id = f"local-{uuid.uuid4().hex[:8]}"
        review_root = self._review_root() / "pull-requests"
        review_root.mkdir(parents=True, exist_ok=True)
        review_path = review_root / f"{review_id}.md"
        payload = {
            "id": review_id,
            "number": review_id,
            "repository_id": repository_id,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "mode": "local-review",
            "created_at": self._utc_now(),
            "url": str(review_path),
            "html_url": str(review_path),
        }
        review_path.write_text(self._render_review_markdown(payload), encoding="utf-8")
        return payload

    def list_pull_request_comments(
        self,
        repository_id: str,
        pull_request_id: int | str,
    ) -> list[dict[str, Any]]:
        del repository_id
        replies_path = self._review_root() / "pr-replies" / f"{self._safe_name(str(pull_request_id))}.jsonl"
        if not replies_path.exists():
            return []
        items: list[dict[str, Any]] = []
        for index, line in enumerate(replies_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            items.append(
                {
                    "thread_id": str(index),
                    "thread_status": "active",
                    "comment_id": index,
                    "content": payload.get("content"),
                    "published_date": payload.get("created_at"),
                    "author": {"displayName": payload.get("author") or "ClawHarness"},
                }
            )
        return items

    def reply_to_pull_request(
        self,
        repository_id: str,
        pull_request_id: int | str,
        *,
        thread_id: int | str,
        content: str,
        parent_comment_id: int = 0,
    ) -> dict[str, Any]:
        del repository_id
        replies_path = self._review_root() / "pr-replies" / f"{self._safe_name(str(pull_request_id))}.jsonl"
        replies_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "id": uuid.uuid4().hex[:8],
            "pull_request_id": str(pull_request_id),
            "thread_id": str(thread_id),
            "parent_comment_id": parent_comment_id,
            "content": content,
            "created_at": self._utc_now(),
            "author": "ClawHarness",
        }
        with replies_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"id": entry["id"], "path": str(replies_path)}

    def get_ci_run(
        self,
        ci_run_id: int | str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        del ci_run_id, repo_id
        raise LocalTaskProviderError("Local-task provider does not support CI runs")

    def retry_ci_run(
        self,
        ci_run_id: int | str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        del ci_run_id, repo_id
        raise LocalTaskProviderError("Local-task provider does not support CI retries")

    def _resolve_repository_path(self, repository_id: str | None) -> Path:
        candidate = Path(repository_id).resolve() if repository_id else self.repository_path
        if candidate is None:
            raise LocalTaskProviderError("Local-task provider requires repository_path or repo_id")
        if not candidate.exists():
            raise LocalTaskProviderError(f"Local repository path does not exist: {candidate}")
        return candidate

    def _resolve_task_file(self, task_id: str) -> Path:
        raw = Path(task_id)
        if raw.is_absolute():
            if not raw.exists():
                raise LocalTaskProviderError(f"Local task file does not exist: {raw}")
            return raw
        roots = [root for root in (self.task_directory, Path.cwd()) if root is not None]
        direct_candidates: list[Path] = []
        if raw.suffix or raw.parts[:-1]:
            direct_candidates.extend(root / raw for root in roots)
            direct_candidates.append(raw.resolve())
        else:
            for root in roots:
                direct_candidates.extend(
                    [
                        root / task_id,
                        root / f"{task_id}.json",
                        root / f"{task_id}.md",
                        root / f"{task_id}.txt",
                    ]
                )
        for candidate in direct_candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        raise LocalTaskProviderError(f"Could not resolve local task file for task_id `{task_id}`")

    def _load_task_payload(self, task_file: Path) -> dict[str, Any]:
        if task_file.suffix.lower() == ".json":
            payload = json.loads(task_file.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise LocalTaskProviderError(f"Local task JSON must be an object: {task_file}")
            return dict(payload)
        content = task_file.read_text(encoding="utf-8")
        return {"title": self._title_from_text(task_file, content), "description": content, "state": "New"}

    def _task_title(self, task_file: Path, payload: Mapping[str, Any]) -> str:
        for key in ("title", "name", "summary"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        fields = payload.get("fields")
        if isinstance(fields, Mapping):
            title = fields.get("System.Title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return task_file.stem

    def _task_description(self, task_file: Path, payload: Mapping[str, Any]) -> str:
        for key in ("description", "body", "content"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        fields = payload.get("fields")
        if isinstance(fields, Mapping):
            description = fields.get("System.Description")
            if isinstance(description, str):
                return description
        return task_file.read_text(encoding="utf-8")

    def _task_state(self, payload: Mapping[str, Any]) -> str:
        for key in ("state", "status"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        fields = payload.get("fields")
        if isinstance(fields, Mapping):
            state = fields.get("System.State")
            if isinstance(state, str) and state.strip():
                return state.strip()
        return "New"

    def _review_root(self) -> Path:
        if self.review_directory is not None:
            return self.review_directory
        if self.task_directory is not None:
            return self.task_directory / ".clawharness-review"
        if self.repository_path is not None:
            return self.repository_path / ".clawharness-review"
        return Path.cwd() / ".clawharness-review"

    def _detect_default_branch(self, repo_path: Path) -> str:
        head = self._run_git(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo_path, allow_failure=True)
        branch = head.stdout.strip()
        if branch:
            return self._normalize_branch_ref(branch)
        return "refs/heads/main"

    def _render_review_markdown(self, payload: Mapping[str, Any]) -> str:
        return "\n".join(
            [
                f"# {payload['title']}",
                "",
                f"- Review ID: `{payload['id']}`",
                f"- Repository: `{payload['repository_id']}`",
                f"- Source Branch: `{payload['source_branch']}`",
                f"- Target Branch: `{payload['target_branch']}`",
                f"- Created At: `{payload['created_at']}`",
                "",
                "## Description",
                "",
                str(payload["description"]),
                "",
                "## Offline Notes",
                "",
                "- This review artifact was generated by the local-task provider.",
                "- No remote PR platform was contacted.",
                "- Review comments can be appended under `.clawharness-review/pr-replies/`.",
            ]
        )

    def _title_from_text(self, task_file: Path, content: str) -> str:
        for line in content.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped
        return task_file.stem

    def _workspace_name(self, repo_name: str, run_id: str) -> str:
        safe_repo = self._safe_name(repo_name) or "repo"
        safe_run = self._safe_name(run_id) or "run"
        return f"{safe_repo}-{safe_run}"

    def _safe_name(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")

    def _normalize_branch_ref(self, branch: str) -> str:
        if branch.startswith("refs/heads/"):
            return branch
        return f"refs/heads/{branch}"

    def _branch_short_name(self, branch: str) -> str:
        return self._normalize_branch_ref(branch).removeprefix("refs/heads/")

    def _run_git(
        self,
        command: list[str],
        *,
        cwd: str | Path | None,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        completed = self.shell_runner(command, cwd, {"GIT_TERMINAL_PROMPT": "0"})
        if completed.returncode != 0 and not allow_failure:
            raise LocalTaskProviderError(
                f"Git command failed: {' '.join(command)}",
                response_body=(completed.stderr or completed.stdout or "").strip() or None,
            )
        return completed

    def _default_shell_runner(
        self,
        command: list[str],
        cwd: str | Path | None,
        env: Mapping[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = {**os.environ, **dict(env or {})}
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=merged_env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
