from __future__ import annotations

import base64
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

NormalizedAdoEvent = NormalizedProviderEvent


class AzureDevOpsApiError(ProviderApiError):
    pass


class AzureDevOpsRestClient:
    provider_type = "azure-devops"
    display_name = "Azure DevOps"

    def __init__(
        self,
        *,
        base_url: str,
        project: str,
        pat: str | None = None,
        api_version: str = "7.1",
        comment_api_version: str = "7.0-preview.3",
        transport: Transport | None = None,
        shell_runner: ShellRunner | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.project = project.strip("/")
        self.pat = pat
        self.api_version = api_version
        self.comment_api_version = comment_api_version
        self.transport = transport or self._default_transport
        self.shell_runner = shell_runner or self._default_shell_runner

    def get_task(
        self,
        work_item_id: int | str,
        *,
        repo_id: str | None = None,
        fields: list[str] | None = None,
        expand: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        del repo_id
        query: dict[str, Any] = {}
        if fields:
            query["fields"] = ",".join(fields)
        if expand:
            query["$expand"] = expand
        if as_of:
            query["asOf"] = as_of
        return self._request_json(
            "GET",
            f"_apis/wit/workitems/{work_item_id}",
            query=query,
        )

    def update_task_fields(
        self,
        work_item_id: int | str,
        operations: list[dict[str, Any]],
        *,
        validate_only: bool = False,
        bypass_rules: bool = False,
        suppress_notifications: bool = False,
        expand: str | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if validate_only:
            query["validateOnly"] = "true"
        if bypass_rules:
            query["bypassRules"] = "true"
        if suppress_notifications:
            query["suppressNotifications"] = "true"
        if expand:
            query["$expand"] = expand
        return self._request_json(
            "PATCH",
            f"_apis/wit/workitems/{work_item_id}",
            query=query,
            body=operations,
            headers={"Content-Type": "application/json-patch+json"},
        )

    def add_task_comment(
        self,
        work_item_id: int | str,
        text: str,
        *,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        del repo_id
        return self._request_json(
            "POST",
            f"_apis/wit/workItems/{work_item_id}/comments",
            api_version=self.comment_api_version,
            body={"text": text},
        )

    def complete_task(
        self,
        work_item_id: int | str,
        *,
        repo_id: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        del repo_id
        last_error: AzureDevOpsApiError | None = None
        updated_task: dict[str, Any] | None = None
        for target_state in ("Done", "Closed"):
            try:
                updated_task = self.update_task_fields(
                    work_item_id,
                    [
                        {"op": "add", "path": "/fields/System.State", "value": target_state},
                    ],
                )
                break
            except AzureDevOpsApiError as exc:
                last_error = exc
        if updated_task is None:
            assert last_error is not None
            raise last_error
        if comment:
            self.add_task_comment(work_item_id, comment)
        return updated_task

    def list_repositories(self) -> list[RepositoryInfo]:
        response = self._request_json("GET", "_apis/git/repositories")
        return [self._repository_from_mapping(item) for item in response.get("value", [])]

    def get_repository(self, repository_id: str) -> RepositoryInfo:
        response = self._request_json("GET", f"_apis/git/repositories/{repository_id}")
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
            raise AzureDevOpsApiError(f"Workspace already exists for run {run_id}: {workspace_path}")

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
        branch_short = self._branch_short_name(branch_ref)

        status = self._run_git(["git", "status", "--short"], cwd=workspace)
        created_commit = bool(status.stdout.strip())
        if not created_commit and not allow_empty:
            raise AzureDevOpsApiError(f"No changes to commit in workspace {workspace}")

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
        push_command = self._git_command(["push", "-u", "origin", f"HEAD:{branch_ref}"])
        self._run_git(push_command, cwd=workspace)
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
        query: dict[str, Any] = {}
        if supports_iterations is not None:
            query["supportsIterations"] = "true" if supports_iterations else "false"
        body: dict[str, Any] = {
            "sourceRefName": source_branch,
            "targetRefName": target_branch,
            "title": title,
            "description": description,
        }
        if reviewers:
            body["reviewers"] = reviewers
        return self._request_json(
            "POST",
            f"_apis/git/repositories/{repository_id}/pullrequests",
            query=query,
            body=body,
        )

    def get_pull_request(self, repository_id: str, pull_request_id: int | str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"_apis/git/repositories/{repository_id}/pullrequests/{pull_request_id}",
        )

    def list_pull_request_threads(self, repository_id: str, pull_request_id: int | str) -> list[dict[str, Any]]:
        response = self._request_json(
            "GET",
            f"_apis/git/repositories/{repository_id}/pullRequests/{pull_request_id}/threads",
        )
        return response.get("value", [])

    def list_pull_request_comments(self, repository_id: str, pull_request_id: int | str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        for thread in self.list_pull_request_threads(repository_id, pull_request_id):
            thread_id = thread.get("id")
            thread_status = thread.get("status")
            for comment in thread.get("comments", []):
                if comment.get("isDeleted"):
                    continue
                comments.append(
                    {
                        "thread_id": thread_id,
                        "thread_status": thread_status,
                        "comment_id": comment.get("id"),
                        "parent_comment_id": comment.get("parentCommentId"),
                        "content": comment.get("content"),
                        "author": comment.get("author"),
                        "published_date": comment.get("publishedDate"),
                        "last_updated_date": comment.get("lastUpdatedDate"),
                    }
                )
        return comments

    def reply_to_pull_request(
        self,
        repository_id: str,
        pull_request_id: int | str,
        *,
        thread_id: int | str,
        content: str,
        parent_comment_id: int = 0,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"_apis/git/repositories/{repository_id}/pullRequests/{pull_request_id}/threads/{thread_id}/comments",
            body={
                "content": content,
                "parentCommentId": parent_comment_id,
                "commentType": 1,
            },
        )

    def get_build(self, build_id: int | str) -> dict[str, Any]:
        return self._request_json("GET", f"_apis/build/builds/{build_id}")

    def get_ci_run(self, ci_run_id: int | str, *, repo_id: str | None = None) -> dict[str, Any]:
        del repo_id
        return self.get_build(ci_run_id)

    def list_builds(
        self,
        *,
        definition_ids: list[int] | None = None,
        branch_name: str | None = None,
        build_ids: list[int] | None = None,
        status_filter: str | None = None,
        result_filter: str | None = None,
        top: int | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if definition_ids:
            query["definitions"] = ",".join(str(item) for item in definition_ids)
        if branch_name:
            query["branchName"] = branch_name
        if build_ids:
            query["buildIds"] = ",".join(str(item) for item in build_ids)
        if status_filter:
            query["statusFilter"] = status_filter
        if result_filter:
            query["resultFilter"] = result_filter
        if top is not None:
            query["$top"] = str(top)
        response = self._request_json("GET", "_apis/build/builds", query=query)
        return response.get("value", [])

    def queue_build(
        self,
        *,
        definition_id: int,
        source_branch: str | None = None,
        source_version: str | None = None,
        parameters: dict[str, Any] | str | None = None,
        queue_id: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "definition": {"id": definition_id},
        }
        if source_branch:
            body["sourceBranch"] = source_branch
        if source_version:
            body["sourceVersion"] = source_version
        if parameters is not None:
            body["parameters"] = parameters if isinstance(parameters, str) else json.dumps(parameters, sort_keys=True)
        if queue_id is not None:
            body["queue"] = {"id": queue_id}
        return self._request_json("POST", "_apis/build/builds", body=body)

    def retry_build(self, build_id: int | str) -> dict[str, Any]:
        existing = self.get_build(build_id)
        definition = existing.get("definition") or {}
        definition_id = definition.get("id")
        if definition_id is None:
            raise AzureDevOpsApiError("Cannot retry build without definition id")

        return self.queue_build(
            definition_id=int(definition_id),
            source_branch=existing.get("sourceBranch"),
            source_version=existing.get("sourceVersion"),
            parameters=existing.get("parameters"),
        )

    def retry_ci_run(self, ci_run_id: int | str, *, repo_id: str | None = None) -> dict[str, Any]:
        del repo_id
        existing = self.get_build(ci_run_id)
        definition = existing.get("definition") or {}
        definition_id = definition.get("id")
        if definition_id is None:
            raise AzureDevOpsApiError("Cannot retry CI run without definition id")
        queue = existing.get("queue") or {}
        queue_id = queue.get("id")

        # CI recovery should validate the latest branch tip after the harness pushes a fix,
        # so avoid pinning the rerun to the failed build's old sourceVersion while
        # preserving the effective queue (for example a self-hosted pool override).
        return self.queue_build(
            definition_id=int(definition_id),
            source_branch=existing.get("sourceBranch"),
            parameters=existing.get("parameters"),
            queue_id=int(queue_id) if queue_id is not None else None,
        )

    def normalize_event(
        self,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        source_id: str | None = None,
    ) -> NormalizedAdoEvent:
        resource = payload.get("resource") if isinstance(payload.get("resource"), Mapping) else payload
        actor = self._normalize_actor(resource, payload)

        task_id = self._pick_value(
            resource,
            [
                "workItemId",
                "id",
                "work_item_id",
            ],
        )
        pr_id = self._pick_value(resource, ["pullRequestId", "pull_request_id", "artifactId"])
        ci_run_id = self._pick_value(resource, ["buildId", "id", "runId"])

        resource_containers = payload.get("resourceContainers")
        repo_id = None
        if isinstance(resource_containers, Mapping):
            repository = resource_containers.get("repository")
            if isinstance(repository, Mapping):
                repo_id = self._pick_value(repository, ["id"])
        if repo_id is None:
            repo = resource.get("repository")
            if isinstance(repo, Mapping):
                repo_id = self._pick_value(repo, ["id"])

        normalized_event_type = self._normalize_event_type(event_type=event_type, resource=resource)
        task_key = self._derive_task_key(payload, resource, task_id)

        return NormalizedAdoEvent(
            event_type=normalized_event_type,
            provider_type=self.provider_type,
            source_id=source_id or self._pick_value(payload, ["id", "eventId"]),
            task_id=str(task_id) if task_id is not None else None,
            task_key=task_key,
            repo_id=str(repo_id) if repo_id is not None else None,
            pr_id=str(pr_id) if pr_id is not None else None,
            ci_run_id=str(ci_run_id) if self._looks_like_build_event(event_type, resource) and ci_run_id is not None else None,
            chat_thread_id=None,
            actor=actor,
            payload=dict(payload),
        )

    def _normalize_event_type(self, *, event_type: str, resource: Mapping[str, Any]) -> str:
        normalized = str(event_type or "").strip()
        if not normalized:
            return normalized
        if self._is_pull_request_merged_event(event_type=normalized, resource=resource):
            return "pr.merged"
        return normalized

    def _is_pull_request_merged_event(self, *, event_type: str, resource: Mapping[str, Any]) -> bool:
        if self._pick_value(resource, ["pullRequestId", "pull_request_id", "artifactId"]) is None:
            return False
        event_key = event_type.replace("-", "").replace("_", "").lower()
        if not (event_key.startswith("pr.") or "pullrequest" in event_key):
            return False
        status = str(resource.get("status") or "").strip().lower()
        merge_status = str(resource.get("mergeStatus") or resource.get("merge_status") or "").strip().lower()
        return status == "completed" and merge_status == "succeeded"

    def _repository_from_mapping(self, payload: Mapping[str, Any]) -> RepositoryInfo:
        repository_id = payload.get("id")
        name = payload.get("name")
        default_branch = payload.get("defaultBranch")
        remote_url = payload.get("remoteUrl")
        if not isinstance(repository_id, str) or not repository_id:
            raise AzureDevOpsApiError("Repository payload missing id")
        if not isinstance(name, str) or not name:
            raise AzureDevOpsApiError("Repository payload missing name")
        if not isinstance(default_branch, str) or not default_branch:
            raise AzureDevOpsApiError("Repository payload missing defaultBranch")
        if not isinstance(remote_url, str) or not remote_url:
            raise AzureDevOpsApiError("Repository payload missing remoteUrl")
        web_url = payload.get("webUrl")
        return RepositoryInfo(
            repository_id=repository_id,
            name=name,
            default_branch=default_branch,
            remote_url=remote_url,
            web_url=str(web_url) if isinstance(web_url, str) else None,
        )

    def _derive_task_key(self, payload: Mapping[str, Any], resource: Mapping[str, Any], task_id: Any) -> str | None:
        direct = payload.get("task_key") or resource.get("task_key")
        if isinstance(direct, str):
            return direct

        if task_id is None:
            return None

        fields = resource.get("fields")
        if isinstance(fields, Mapping):
            project_name = fields.get("System.TeamProject")
            if isinstance(project_name, str) and project_name:
                return f"{project_name}#{task_id}"

        return str(task_id)

    def _normalize_actor(self, resource: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
        candidates = [
            resource.get("revisedBy"),
            resource.get("createdBy"),
            resource.get("requestedBy"),
            payload.get("resourceVersion"),
            payload.get("createdBy"),
        ]
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                actor_id = candidate.get("id") or candidate.get("descriptor")
                actor_name = candidate.get("displayName") or candidate.get("uniqueName") or candidate.get("name")
                if actor_id is not None or actor_name is not None:
                    return {
                        "id": actor_id,
                        "name": actor_name,
                    }
        return {"id": None, "name": None}

    def _looks_like_build_event(self, event_type: str, resource: Mapping[str, Any]) -> bool:
        if event_type.startswith("ci.") or event_type.startswith("build."):
            return True
        return "definition" in resource and "status" in resource and "result" in resource

    def _pick_value(self, mapping: Mapping[str, Any], keys: list[str]) -> Any:
        for key in keys:
            if key in mapping and mapping[key] is not None:
                return mapping[key]
        return None

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: dict[str, str] | None = None,
        api_version: str | None = None,
    ) -> dict[str, Any]:
        data = self._request(method, path, query=query, body=body, headers=headers, api_version=api_version)
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
        api_version: str | None = None,
    ) -> bytes:
        url = self._build_url(path, query=query, api_version=api_version)
        merged_headers = self._default_headers()
        if headers:
            merged_headers.update(headers)

        encoded_body: bytes | None = None
        if body is not None:
            encoded_body = json.dumps(body).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")

        status_code, _response_headers, content = self.transport(method, url, merged_headers, encoded_body)
        if status_code >= 400:
            raise AzureDevOpsApiError(
                f"Azure DevOps request failed: {method} {url}",
                status_code=status_code,
                response_body=content.decode("utf-8", errors="replace"),
            )
        return content

    def _build_url(
        self,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        api_version: str | None = None,
    ) -> str:
        base = f"{self.base_url}/{self.project}/{path.lstrip('/')}"
        all_query = {"api-version": api_version or self.api_version}
        if query:
            for key, value in query.items():
                if value is not None:
                    all_query[key] = value
        encoded_query = parse.urlencode(all_query, doseq=True, safe="$/,:")
        return f"{base}?{encoded_query}"

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
        }
        if self.pat:
            token = base64.b64encode(f":{self.pat}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
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
            raise AzureDevOpsApiError(f"Azure DevOps request transport failed: {exc}") from exc

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
        if self.pat:
            command.extend(["-c", f"http.extraheader=Authorization: Basic {self._basic_pat_token()}"])
        command.extend(args)
        return command

    def _basic_pat_token(self) -> str:
        return base64.b64encode(f":{self.pat or ''}".encode("utf-8")).decode("ascii")

    def _run_git(self, command: list[str], *, cwd: str | Path) -> subprocess.CompletedProcess[str]:
        result = self.shell_runner(command, cwd, {"GIT_TERMINAL_PROMPT": "0"})
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise AzureDevOpsApiError(f"Git command failed in {cwd}: {stderr or 'unknown error'}")
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
