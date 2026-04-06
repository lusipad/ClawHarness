from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import parse, request
from urllib.error import HTTPError, URLError

from workflow_provider import (
    CommitPushResult,
    NormalizedProviderEvent,
    ProviderApiError,
    RepositoryInfo,
    WorkspacePreparationResult,
)


Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Mapping[str, str], bytes]]
ShellRunner = Callable[[list[str], str | Path | None, Mapping[str, str] | None], subprocess.CompletedProcess[str]]


class GitHubApiError(ProviderApiError):
    pass


class GitHubRestClient:
    provider_type = "github"
    display_name = "GitHub"

    def __init__(
        self,
        *,
        base_url: str = "https://api.github.com",
        token: str | None = None,
        api_version: str = "2022-11-28",
        transport: Transport | None = None,
        shell_runner: ShellRunner | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.api_version = api_version
        self.transport = transport or self._default_transport
        self.shell_runner = shell_runner or self._default_shell_runner

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
        repository_id = self._require_repo_id(repo_id)
        issue = self._request_json("GET", f"repos/{repository_id}/issues/{task_id}")
        labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []
        return {
            "id": issue.get("number", task_id),
            "number": issue.get("number", task_id),
            "repository": repository_id,
            "html_url": issue.get("html_url"),
            "fields": {
                "System.TeamProject": repository_id,
                "System.Title": issue.get("title") or "",
                "System.Description": issue.get("body") or "",
                "System.State": issue.get("state") or "",
                "GitHub.Labels": [label.get("name") for label in labels if isinstance(label, Mapping)],
                "GitHub.Assignees": [
                    item.get("login")
                    for item in issue.get("assignees", [])
                    if isinstance(item, Mapping) and item.get("login")
                ],
                "GitHub.HTMLURL": issue.get("html_url"),
            },
        }

    def add_task_comment(
        self,
        task_id: int | str,
        text: str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        repository_id = self._require_repo_id(repo_id)
        return self._request_json(
            "POST",
            f"repos/{repository_id}/issues/{task_id}/comments",
            body={"body": text},
        )

    def get_repository(self, repository_id: str) -> RepositoryInfo:
        response = self._request_json("GET", f"repos/{repository_id}")
        return self._repository_from_mapping(response)

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
            raise GitHubApiError(f"Workspace already exists for run {run_id}: {workspace_path}")

        clone_command = self._git_command(
            [
                "clone",
                "--origin",
                "origin",
                "--branch",
                self._branch_short_name(repository.default_branch),
                repository.remote_url,
                str(workspace_path),
            ]
        )
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

        self._run_git(self._git_command(["fetch", "origin", base_ref]), cwd=workspace)
        self._run_git(self._git_command(["checkout", "-B", branch_short, f"origin/{base_short}"]), cwd=workspace)
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
            raise GitHubApiError(f"No changes to commit in workspace {workspace}")

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
        self._run_git(self._git_command(["push", "-u", "origin", f"HEAD:{branch_ref}"]), cwd=workspace)
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
        return self._request_json(
            "POST",
            f"repos/{repository_id}/pulls",
            body={
                "title": title,
                "head": self._branch_short_name(source_branch),
                "base": self._branch_short_name(target_branch),
                "body": description,
            },
        )

    def list_pull_request_comments(
        self,
        repository_id: str,
        pull_request_id: int | str,
    ) -> list[dict[str, Any]]:
        review_comments = self._request_json(
            "GET",
            f"repos/{repository_id}/pulls/{pull_request_id}/comments",
            query={"per_page": "100"},
        )
        issue_comments = self._request_json(
            "GET",
            f"repos/{repository_id}/issues/{pull_request_id}/comments",
            query={"per_page": "100"},
        )
        items: list[dict[str, Any]] = []
        for comment in review_comments if isinstance(review_comments, list) else []:
            if not isinstance(comment, Mapping):
                continue
            items.append(
                {
                    "thread_id": str(comment.get("id") or ""),
                    "thread_status": "active",
                    "comment_id": comment.get("id"),
                    "parent_comment_id": comment.get("in_reply_to_id"),
                    "content": comment.get("body"),
                    "author": comment.get("user"),
                    "published_date": comment.get("created_at"),
                    "last_updated_date": comment.get("updated_at"),
                    "comment_type": "review",
                }
            )
        for comment in issue_comments if isinstance(issue_comments, list) else []:
            if not isinstance(comment, Mapping):
                continue
            items.append(
                {
                    "thread_id": f"issue-comment:{comment.get('id')}",
                    "thread_status": "active",
                    "comment_id": comment.get("id"),
                    "parent_comment_id": None,
                    "content": comment.get("body"),
                    "author": comment.get("user"),
                    "published_date": comment.get("created_at"),
                    "last_updated_date": comment.get("updated_at"),
                    "comment_type": "issue",
                }
            )
        items.sort(key=lambda item: str(item.get("published_date") or ""))
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
        thread_key = str(thread_id)
        if thread_key.startswith("issue-comment:"):
            return self._request_json(
                "POST",
                f"repos/{repository_id}/issues/{pull_request_id}/comments",
                body={"body": content},
            )
        if parent_comment_id > 0:
            return self._request_json(
                "POST",
                f"repos/{repository_id}/pulls/{pull_request_id}/comments/{parent_comment_id}/replies",
                body={"body": content},
            )
        return self._request_json(
            "POST",
            f"repos/{repository_id}/issues/{pull_request_id}/comments",
            body={"body": content},
        )

    def get_ci_run(
        self,
        ci_run_id: int | str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        repository_id = self._require_repo_id(repo_id)
        kind, raw_id = self._split_ci_run_id(ci_run_id)
        if kind == "check-suite":
            return self._request_json("GET", f"repos/{repository_id}/check-suites/{raw_id}")
        return self._request_json("GET", f"repos/{repository_id}/check-runs/{raw_id}")

    def retry_ci_run(
        self,
        ci_run_id: int | str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        repository_id = self._require_repo_id(repo_id)
        kind, raw_id = self._split_ci_run_id(ci_run_id)
        if kind == "check-suite":
            self._request_json("POST", f"repos/{repository_id}/check-suites/{raw_id}/rerequest")
            return {"id": f"check-suite:{raw_id}"}
        self._request_json("POST", f"repos/{repository_id}/check-runs/{raw_id}/rerequest")
        return {"id": f"check-run:{raw_id}"}

    def normalize_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> NormalizedProviderEvent:
        repository = payload.get("repository") if isinstance(payload.get("repository"), Mapping) else {}
        repo_id = self._repository_full_name(repository)
        actor = self._normalize_actor(payload)
        action = str(payload.get("action") or "").strip().lower()

        if event_type == "issues":
            issue = payload.get("issue") if isinstance(payload.get("issue"), Mapping) else {}
            if action in {"opened", "reopened"} and "pull_request" not in issue:
                issue_number = issue.get("number")
                return self._event(
                    normalized_event_type="task.created",
                    source_id=source_id,
                    task_id=issue_number,
                    task_key=self._task_key(repo_id, issue_number),
                    repo_id=repo_id,
                    pr_id=None,
                    ci_run_id=None,
                    actor=actor,
                    payload=payload,
                )

        if event_type == "issue_comment":
            issue = payload.get("issue") if isinstance(payload.get("issue"), Mapping) else {}
            if "pull_request" in issue and action in {"created", "edited"}:
                pr_number = issue.get("number")
                return self._event(
                    normalized_event_type="pr.comment.created",
                    source_id=source_id,
                    task_id=None,
                    task_key=None,
                    repo_id=repo_id,
                    pr_id=pr_number,
                    ci_run_id=None,
                    actor=actor,
                    payload=payload,
                )

        if event_type == "pull_request_review_comment":
            pull_request = payload.get("pull_request") if isinstance(payload.get("pull_request"), Mapping) else {}
            if action in {"created", "edited"}:
                pr_number = pull_request.get("number")
                return self._event(
                    normalized_event_type="pr.comment.created",
                    source_id=source_id,
                    task_id=None,
                    task_key=None,
                    repo_id=repo_id,
                    pr_id=pr_number,
                    ci_run_id=None,
                    actor=actor,
                    payload=payload,
                )

        if event_type == "check_run":
            check_run = payload.get("check_run") if isinstance(payload.get("check_run"), Mapping) else {}
            conclusion = str(check_run.get("conclusion") or "").strip().lower()
            if action == "completed" and conclusion in {"failure", "timed_out", "action_required", "stale", "cancelled"}:
                pr_number = self._pull_request_number(check_run)
                ci_run_id = check_run.get("id")
                return self._event(
                    normalized_event_type="ci.run.failed",
                    source_id=source_id,
                    task_id=None,
                    task_key=None,
                    repo_id=repo_id,
                    pr_id=pr_number,
                    ci_run_id=f"check-run:{ci_run_id}" if ci_run_id is not None else None,
                    actor=actor,
                    payload=payload,
                )

        if event_type == "check_suite":
            check_suite = payload.get("check_suite") if isinstance(payload.get("check_suite"), Mapping) else {}
            conclusion = str(check_suite.get("conclusion") or "").strip().lower()
            if action == "completed" and conclusion in {"failure", "timed_out", "action_required", "stale", "cancelled"}:
                pr_number = self._pull_request_number(check_suite)
                ci_run_id = check_suite.get("id")
                return self._event(
                    normalized_event_type="ci.run.failed",
                    source_id=source_id,
                    task_id=None,
                    task_key=None,
                    repo_id=repo_id,
                    pr_id=pr_number,
                    ci_run_id=f"check-suite:{ci_run_id}" if ci_run_id is not None else None,
                    actor=actor,
                    payload=payload,
                )

        return self._event(
            normalized_event_type=f"github.{event_type}.{action or 'unknown'}",
            source_id=source_id,
            task_id=None,
            task_key=None,
            repo_id=repo_id,
            pr_id=None,
            ci_run_id=None,
            actor=actor,
            payload=payload,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any]:
        data = self._request(method, path, query=query, body=body, headers=headers)
        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        url = self._build_url(path, query=query)
        merged_headers = self._default_headers()
        if headers:
            merged_headers.update(headers)

        encoded_body: bytes | None = None
        if body is not None:
            encoded_body = json.dumps(body).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")

        status_code, _response_headers, content = self.transport(method, url, merged_headers, encoded_body)
        if status_code >= 400:
            raise GitHubApiError(
                f"GitHub request failed: {method} {url}",
                status_code=status_code,
                response_body=content.decode("utf-8", errors="replace"),
            )
        return content

    def _build_url(self, path: str, *, query: Mapping[str, Any] | None = None) -> str:
        base = f"{self.base_url}/{path.lstrip('/')}"
        if not query:
            return base
        return f"{base}?{parse.urlencode(query, doseq=True, safe='/:')}"

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

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
            raise GitHubApiError(f"GitHub request transport failed: {exc}") from exc

    def _repository_from_mapping(self, payload: Mapping[str, Any]) -> RepositoryInfo:
        full_name = self._repository_full_name(payload)
        name = payload.get("name")
        default_branch = payload.get("default_branch")
        remote_url = payload.get("clone_url")
        if not full_name:
            raise GitHubApiError("Repository payload missing full_name")
        if not isinstance(name, str) or not name:
            raise GitHubApiError("Repository payload missing name")
        if not isinstance(default_branch, str) or not default_branch:
            raise GitHubApiError("Repository payload missing default_branch")
        if not isinstance(remote_url, str) or not remote_url:
            raise GitHubApiError("Repository payload missing clone_url")
        web_url = payload.get("html_url")
        return RepositoryInfo(
            repository_id=full_name,
            name=name,
            default_branch=self._normalize_branch_ref(default_branch),
            remote_url=remote_url,
            web_url=str(web_url) if isinstance(web_url, str) else None,
        )

    def _normalize_actor(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        sender = payload.get("sender")
        if isinstance(sender, Mapping):
            return {"id": sender.get("id"), "name": sender.get("login")}
        return {"id": None, "name": None}

    def _event(
        self,
        *,
        normalized_event_type: str,
        source_id: str | None,
        task_id: Any,
        task_key: str | None,
        repo_id: str | None,
        pr_id: Any,
        ci_run_id: str | None,
        actor: dict[str, Any],
        payload: Mapping[str, Any],
    ) -> NormalizedProviderEvent:
        return NormalizedProviderEvent(
            event_type=normalized_event_type,
            provider_type=self.provider_type,
            source_id=source_id or self._pick_value(payload, ["delivery", "id"]),
            task_id=str(task_id) if task_id is not None else None,
            task_key=task_key,
            repo_id=repo_id,
            pr_id=str(pr_id) if pr_id is not None else None,
            ci_run_id=ci_run_id,
            chat_thread_id=None,
            actor=actor,
            payload=dict(payload),
        )

    def _pull_request_number(self, payload: Mapping[str, Any]) -> Any:
        pull_requests = payload.get("pull_requests")
        if isinstance(pull_requests, list):
            for item in pull_requests:
                if not isinstance(item, Mapping):
                    continue
                number = item.get("number")
                if number is not None:
                    return number
        pull_request = payload.get("pull_request")
        if isinstance(pull_request, Mapping):
            return pull_request.get("number")
        return None

    def _repository_full_name(self, payload: Mapping[str, Any]) -> str | None:
        full_name = payload.get("full_name")
        if isinstance(full_name, str) and full_name:
            return full_name
        owner = payload.get("owner")
        owner_name = None
        if isinstance(owner, Mapping):
            owner_name = owner.get("login") or owner.get("name")
        name = payload.get("name")
        if isinstance(owner_name, str) and owner_name and isinstance(name, str) and name:
            return f"{owner_name}/{name}"
        return None

    def _task_key(self, repo_id: str | None, issue_number: Any) -> str | None:
        if repo_id is None or issue_number is None:
            return None
        return f"{repo_id}#{issue_number}"

    def _pick_value(self, mapping: Mapping[str, Any], keys: list[str]) -> Any:
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return value
        return None

    def _require_repo_id(self, repo_id: str | None) -> str:
        if not isinstance(repo_id, str) or not repo_id.strip():
            raise GitHubApiError("GitHub repository id is required")
        return repo_id.strip()

    def _split_ci_run_id(self, ci_run_id: int | str) -> tuple[str, str]:
        text = str(ci_run_id)
        if ":" in text:
            kind, raw_id = text.split(":", 1)
            return kind, raw_id
        return "check-run", text

    def _workspace_name(self, repository_name: str, run_id: str) -> str:
        repo_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", repository_name).strip("-") or "repo"
        run_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip("-") or "run"
        return f"{repo_slug}-{run_slug}"

    def _normalize_branch_ref(self, branch_name: str) -> str:
        if branch_name.startswith("refs/heads/"):
            return branch_name
        return f"refs/heads/{branch_name}"

    def _branch_short_name(self, branch_name: str) -> str:
        if branch_name.startswith("refs/heads/"):
            return branch_name[len("refs/heads/") :]
        return branch_name

    def _git_command(self, args: list[str]) -> list[str]:
        command = ["git", "-c", "credential.interactive=never", "-c", "core.askPass="]
        if self.token:
            auth_header = self._basic_auth_header()
            command.extend(["-c", f"http.extraheader=Authorization: Basic {auth_header}"])
        command.extend(args)
        return command

    def _basic_auth_header(self) -> str:
        import base64

        return base64.b64encode(f"x-access-token:{self.token or ''}".encode("utf-8")).decode("ascii")

    def _run_git(self, command: list[str], *, cwd: str | Path) -> subprocess.CompletedProcess[str]:
        result = self.shell_runner(command, cwd, {"GIT_TERMINAL_PROMPT": "0"})
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise GitHubApiError(f"Git command failed in {cwd}: {stderr or 'unknown error'}")
        return result

    def _default_shell_runner(
        self,
        command: list[str],
        cwd: str | Path | None,
        env_overrides: Mapping[str, str] | None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
