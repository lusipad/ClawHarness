# Azure DevOps Request List

Status: draft baseline
Mode: `ado-rest`

This document defines the MVP request surface for the Azure DevOps adapter.
All shared flow usage must map to unified capability names. Provider-specific URL paths stay inside `ado_client`.

Implementation note:
- The first `ado_client` code path is Python stdlib based, with no third-party HTTP dependency.
- Endpoint shapes below are aligned to Microsoft Learn Azure DevOps REST references checked on 2026-04-05.
- Work item comments currently require preview version `7.0-preview.3`, while the main work item, Git pull request, and build endpoints use `7.1`.

## Task Capabilities

### `task.list_candidates`

Purpose:
- discover eligible work items when polling is enabled

Expected input:
- project
- query or queue filters
- pagination cursor if needed

Expected output:
- normalized task summaries

### `task.get`

Purpose:
- fetch the task body and metadata needed by `analyze-task`

Expected input:
- task id
- project

Expected output:
- normalized task payload with title, description, repo binding, assignee, tags, and revision

Reference:
- `GET /{project}/_apis/wit/workitems/{id}?api-version=7.1`

### `task.update_status`

Purpose:
- write planning, blocked, PR-opened, or completed state back to Azure DevOps

Expected input:
- task id
- status or state transition
- optional metadata such as run id or PR url

Expected output:
- updated task state

Reference:
- `PATCH /{project}/_apis/wit/workitems/{id}?api-version=7.1`

### `task.add_comment`

Purpose:
- add run summaries, blockers, or completion notes to the work item

Expected input:
- task id
- markdown or plain-text body

Expected output:
- created comment metadata

Reference:
- `POST /{project}/_apis/wit/workItems/{id}/comments?api-version=7.0-preview.3`

## Repository and Version-Control Capabilities

### `repo.prepare_workspace`

Purpose:
- resolve repository metadata and prepare a clean per-run workspace

Expected input:
- repo id
- run id
- workspace root
- branch prefix

Expected output:
- workspace path
- default branch
- repo metadata

### `vcs.create_branch`

Purpose:
- create a task-scoped working branch

Expected input:
- repo id
- base branch
- branch name

Expected output:
- created branch ref

### `vcs.commit_and_push`

Purpose:
- stage changes, create a commit, and push the working branch

Expected input:
- workspace path
- branch name
- commit message

Expected output:
- pushed commit sha
- remote branch url or ref

## Pull Request Capabilities

### `pr.create`

Purpose:
- open the initial PR from the task branch

Expected input:
- repo id
- source branch
- target branch
- title
- description

Expected output:
- PR id
- PR url
- reviewer summary if available

Reference:
- `POST /{project}/_apis/git/repositories/{repositoryId}/pullrequests?api-version=7.1`

### `pr.get`

Purpose:
- fetch current PR state

Expected input:
- repo id
- PR id

Expected output:
- normalized PR summary

Reference:
- `GET /{project}/_apis/git/repositories/{repositoryId}/pullrequests/{pullRequestId}?api-version=7.1`

### `pr.list_comments`

Purpose:
- collect unresolved feedback for the resume loop

Expected input:
- repo id
- PR id

Expected output:
- normalized comment list with status and author metadata

Reference:
- `GET /{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/threads?api-version=7.1`

### `pr.reply`

Purpose:
- post a response after applying review feedback

Expected input:
- repo id
- PR id
- body

Expected output:
- created reply metadata

Reference:
- `POST /{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/threads/{threadId}/comments?api-version=7.1`

## CI Capabilities

### `ci.get_status`

Purpose:
- read validation state for the active PR or run

Expected input:
- repo id
- PR id or CI run id

Expected output:
- normalized CI status summary

Reference:
- `GET /{project}/_apis/build/builds/{buildId}?api-version=7.1`

### `ci.retry`

Purpose:
- rerun a failed validation path when policy allows it

Expected input:
- repo id
- CI run id

Expected output:
- retry request acknowledgement

Reference:
- `POST /{project}/_apis/build/builds?api-version=7.1`

Implementation note:
- Azure DevOps does not expose one single generic "retry this exact failed run" endpoint across all pipeline shapes in the same way as the other APIs above.
- The current baseline implementation re-queues a build from the existing build's `definition.id`, `sourceBranch`, `sourceVersion`, and `parameters`.
- This is a pragmatic MVP inference and should be validated against the target CI configuration before production rollout.

## Normalized Event Contract

Each inbound Azure DevOps event should be normalized before any flow sees it:

```json
{
  "event_type": "task.created",
  "provider": "azure-devops",
  "source_id": "evt-123",
  "task_id": "12345",
  "task_key": "AB#12345",
  "repo_id": "repo-1",
  "pr_id": null,
  "ci_run_id": null,
  "chat_thread_id": null,
  "actor": {
    "id": "user-1",
    "name": "alice"
  },
  "payload": {}
}
```

## Open Questions for Implementation

- Confirm the exact REST endpoints and payload differences for Azure DevOps Services vs Azure DevOps Server.
- Confirm whether branch policy or build status APIs differ enough to require adapter branching.
- Confirm the retry semantics for the target CI configuration.
