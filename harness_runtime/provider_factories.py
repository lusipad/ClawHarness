from __future__ import annotations

from ado_client import AzureDevOpsRestClient
from github_client import GitHubRestClient
from local_client import LocalTaskClient
from workflow_provider import WorkflowProviderClient

from .config import HarnessRuntimeConfig


def create_azure_devops_task_provider(config: HarnessRuntimeConfig) -> WorkflowProviderClient | None:
    if config.azure_devops is None:
        return None
    return AzureDevOpsRestClient(
        base_url=config.azure_devops.base_url,
        project=config.azure_devops.project,
        pat=config.azure_devops.pat,
    )


def create_github_task_provider(config: HarnessRuntimeConfig) -> WorkflowProviderClient | None:
    if config.github is None:
        return None
    return GitHubRestClient(
        base_url=config.github.base_url,
        token=config.github.token,
    )


def create_local_task_provider(config: HarnessRuntimeConfig) -> WorkflowProviderClient | None:
    if config.local_task is None:
        return None
    return LocalTaskClient(
        repository_path=config.local_task.repository_path,
        task_directory=config.local_task.task_directory,
        review_directory=config.local_task.review_directory,
        base_branch=config.local_task.base_branch,
        push_enabled=config.local_task.push_enabled,
    )
