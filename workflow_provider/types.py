from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class NormalizedProviderEvent:
    event_type: str
    provider_type: str
    source_id: str | None
    task_id: str | None
    task_key: str | None
    repo_id: str | None
    pr_id: str | None
    ci_run_id: str | None
    chat_thread_id: str | None
    actor: dict[str, Any]
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepositoryInfo:
    repository_id: str
    name: str
    default_branch: str
    remote_url: str
    web_url: str | None = None


@dataclass(frozen=True)
class WorkspacePreparationResult:
    repository: RepositoryInfo
    workspace_path: str
    base_branch: str


@dataclass(frozen=True)
class CommitPushResult:
    branch_name: str
    commit_sha: str
    remote_ref: str
    created_commit: bool


class ProviderApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@runtime_checkable
class WorkflowProviderClient(Protocol):
    provider_type: str
    display_name: str

    def normalize_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> NormalizedProviderEvent: ...

    def get_task(
        self,
        task_id: int | str,
        *,
        repo_id: str | None = None,
        fields: list[str] | None = None,
        expand: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]: ...

    def add_task_comment(
        self,
        task_id: int | str,
        text: str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]: ...

    def prepare_workspace(
        self,
        repository_id: str,
        *,
        workspace_root: str | Path,
        run_id: str,
    ) -> WorkspacePreparationResult: ...

    def create_branch(
        self,
        workspace_path: str | Path,
        *,
        branch_name: str,
        base_branch: str,
    ) -> str: ...

    def commit_and_push(
        self,
        workspace_path: str | Path,
        *,
        branch_name: str,
        commit_message: str,
        author_name: str = "ClawHarness",
        author_email: str = "clawharness@local.invalid",
        allow_empty: bool = False,
    ) -> CommitPushResult: ...

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
    ) -> dict[str, Any]: ...

    def list_pull_request_comments(
        self,
        repository_id: str,
        pull_request_id: int | str,
    ) -> list[dict[str, Any]]: ...

    def reply_to_pull_request(
        self,
        repository_id: str,
        pull_request_id: int | str,
        *,
        thread_id: int | str,
        content: str,
        parent_comment_id: int = 0,
    ) -> dict[str, Any]: ...

    def get_ci_run(
        self,
        ci_run_id: int | str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]: ...

    def retry_ci_run(
        self,
        ci_run_id: int | str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]: ...
