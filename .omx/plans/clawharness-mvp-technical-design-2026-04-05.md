# ClawHarness MVP Technical Design

Superseded by: `.omx/plans/clawharness-master-plan-2026-04-05.md`

Date: 2026-04-05
Status: MVP technical design
Depends on: `.omx/plans/clawharness-architecture-2026-04-05.md`

## Goal

Define the smallest implementation that can:

- receive work from Azure DevOps
- let OpenClaw analyze and plan it
- dispatch code changes to Codex via ACP
- create a branch and PR
- react to PR comments and CI failures
- notify Rocket.Chat
- deploy in both Docker and non-Docker environments

## MVP Design Decision

For the first release, keep the center of gravity inside OpenClaw.

Use:

- OpenClaw Gateway
- OpenClaw TaskFlow
- OpenClaw hooks and webhooks
- OpenClaw skills
- OpenClaw ACP with Codex
- Azure DevOps tools via MCP or direct adapter

Do not require a separate always-on external orchestrator in v1.

Instead, package a small `harness runtime` with the OpenClaw plugin bundle. This runtime owns:

- run registry
- dedupe
- task locks
- audit trail
- provider configuration

If later scale or network segmentation requires it, this runtime can be moved into a standalone sidecar without changing skill contracts.

## Architecture Summary

```text
Azure DevOps
  -> webhook / poll
     -> OpenClaw webhook hook
        -> harness runtime
           -> TaskFlow start/resume
              -> OpenClaw planning
                 -> Azure DevOps tools
                 -> ACP: Codex
                 -> Rocket.Chat notify
```

## Concrete Technical Decisions

### 1. Control Plane

Use one OpenClaw Gateway instance for MVP.

Reason:

- simplest deployment
- easiest session management
- built-in automation primitives already exist
- no distributed coordination problem in v1

### 2. Coding Executor

Use Codex through OpenClaw ACP in `persistent` mode.

Reason:

- existing ACP support for Codex is already documented
- avoids inventing a new executor protocol
- keeps executor swappable later

### 3. DevOps Provider

Support both Azure DevOps variants behind one internal provider contract:

- `ado-mcp` mode:
  Preferred for Azure DevOps Services where the official Microsoft MCP server is likely the fastest path.
- `ado-rest` mode:
  Preferred fallback for Azure DevOps Server on-prem or missing MCP coverage.

Both modes expose the same skill/tool names.

### 4. Chat Provider

MVP chat mode has two operating profiles:

- `notify-only`:
  Send status updates to Rocket.Chat via webhook. This is the fastest and safest first deployment.
- `threaded-control`:
  Use a Rocket.Chat plugin/bridge path to map a thread back to the OpenClaw session.

Default MVP recommendation:

- start with `notify-only`
- add `threaded-control` after the main task-to-PR loop is stable

### 5. Reliability Store

Use local SQLite for MVP.

Database path:

```text
~/.openclaw/harness/harness.db
```

Reason:

- zero external dependency
- works in Docker and non-Docker modes
- sufficient for single-gateway deployment

Upgrade path:

- move to PostgreSQL only when you need multi-instance coordination

### 6. Workspace Layout

Use one workspace per active task run.

Suggested root:

```text
~/.openclaw/workspace/harness/runs/<provider>/<taskKey>/<runId>/
```

Branch naming:

```text
ai/<provider>/<taskKey>/<shortRunId>
```

Examples:

- `ai/ado/AB#1234/8f29bc1`
- `ai/ado/bug-1234/8f29bc1`

### 7. Packaging Shape

Ship one versioned bundle:

```text
harness-bundle/
  plugins/
  skills/
  hooks/
  providers/
  runtime/
  deploy/
```

This bundle supports:

- Docker compose install
- native host install

## MVP Component Breakdown

### A. ClawHarness Plugin Bundle

This is the primary customization surface.

Contents:

- provider tool adapters
- skills
- TaskFlow definitions
- webhook hooks
- runtime library
- policy config

Recommended sub-layout:

```text
plugins/harness/
  package/
    plugin.json
  src/
    providers/
      ado/
      rocketchat/
      executor/
    runtime/
      db/
      locks/
      events/
      audit/
    skills/
      analyze-task/
      implement-task/
      fix-pr-feedback/
      recover-ci-failure/
    hooks/
      task-ingest/
      pr-feedback/
      ci-failure/
    flows/
      task-run.yaml
      pr-feedback.yaml
      ci-recovery.yaml
```

### B. Harness Runtime

This is a library in v1, not necessarily a separate service.

Responsibilities:

- persist `TaskRun`
- create and release task locks
- store dedupe fingerprints
- store chat thread mappings
- store PR and CI associations
- write audit entries

### C. Provider Adapters

#### DevOps adapter

Exposed internal contract:

- `task.list_candidates`
- `task.get`
- `task.update_status`
- `task.add_comment`
- `repo.prepare_workspace`
- `vcs.create_branch`
- `vcs.commit_and_push`
- `pr.create`
- `pr.get`
- `pr.list_comments`
- `pr.reply`
- `ci.get_status`
- `ci.retry`

Implementation modes:

- `ado-mcp`
- `ado-rest`

#### Chat adapter

Exposed internal contract:

- `chat.post_update`
- `chat.post_error`
- `chat.read_thread`
- `chat.resolve_thread_target`

Implementation modes:

- `rocketchat-webhook`
- `rocketchat-bridge`

#### Executor adapter

Exposed internal contract:

- `executor.run_coding_task`
- `executor.resume_coding_task`
- `executor.cancel_coding_task`

Implementation mode:

- `codex-acp`

## Minimal Data Model

### task_runs

```text
run_id               TEXT PRIMARY KEY
provider_type        TEXT NOT NULL
task_id              TEXT NOT NULL
task_key             TEXT NOT NULL
repo_id              TEXT
branch_name          TEXT
workspace_path       TEXT
pr_id                TEXT
ci_run_id            TEXT
chat_thread_id       TEXT
session_id           TEXT NOT NULL
executor_type        TEXT NOT NULL
status               TEXT NOT NULL
retry_count          INTEGER NOT NULL DEFAULT 0
started_at           TEXT NOT NULL
updated_at           TEXT NOT NULL
last_error           TEXT
```

### event_dedupe

```text
fingerprint          TEXT PRIMARY KEY
source_type          TEXT NOT NULL
source_id            TEXT
received_at          TEXT NOT NULL
expires_at           TEXT NOT NULL
```

### task_locks

```text
lock_key             TEXT PRIMARY KEY
run_id               TEXT NOT NULL
owner                TEXT NOT NULL
acquired_at          TEXT NOT NULL
expires_at           TEXT NOT NULL
```

### run_audit

```text
id                   INTEGER PRIMARY KEY
run_id               TEXT NOT NULL
event_type           TEXT NOT NULL
payload_json         TEXT
created_at           TEXT NOT NULL
```

### thread_links

```text
chat_thread_id       TEXT PRIMARY KEY
run_id               TEXT NOT NULL
session_id           TEXT NOT NULL
provider_type        TEXT NOT NULL
linked_at            TEXT NOT NULL
```

## Status Model

Use this exact status graph in MVP:

```text
queued
  -> claimed
  -> planning
  -> coding
  -> opening_pr
  -> awaiting_ci
  -> awaiting_review
  -> retrying
  -> completed

failure edges:
  -> awaiting_human
  -> failed
  -> cancelled
```

Recommended status semantics:

- `queued`: event accepted, not yet locked
- `claimed`: lock acquired, run created
- `planning`: OpenClaw is analyzing and choosing next steps
- `coding`: Codex is actively executing changes
- `opening_pr`: branch push and PR creation in progress
- `awaiting_ci`: PR open, CI running or pending
- `awaiting_review`: waiting for human or PR review feedback
- `retrying`: system is re-entering after a CI or transient failure
- `awaiting_human`: blocked on missing requirements, risk, or policy
- `completed`: task satisfied for MVP handoff
- `failed`: unrecoverable error
- `cancelled`: explicit stop

## Event Model

### Supported inbound event types

- `task.created`
- `task.updated`
- `pr.comment.created`
- `pr.status.changed`
- `ci.run.failed`
- `ci.run.succeeded`
- `chat.command`

### Event normalization contract

Every inbound provider event should be normalized to:

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

The runtime computes a fingerprint from:

- provider
- event_type
- source_id if present
- fallback hash of stable payload fields

## OpenClaw Trigger Model

### Preferred trigger path

Use OpenClaw webhooks for external event intake where possible.

Relevant OpenClaw capability:

- Gateway webhook endpoint for external triggers
- hooks for event-driven automation
- TaskFlow for durable, resumable flow state

This keeps ingress aligned with OpenClaw instead of introducing a second control plane.

### Trigger flow

1. Azure DevOps webhook hits a small local handler.
2. Handler normalizes payload and stores/claims the run in the runtime store.
3. Handler posts a compact wake event into OpenClaw webhook intake.
4. OpenClaw flow or hook claims the normalized event and resumes the mapped session.

If the installed OpenClaw version exposes enough webhook-hook flexibility, the local handler can be merged into the plugin bundle.

If not, run the handler as a bundled companion process. The contract stays the same.

## TaskFlow Definitions

### Flow 1: `task-run`

Purpose:

- take a task from initial ingestion to PR creation and first CI wait

Steps:

1. validate event and acquire lock
2. fetch task details
3. choose or create OpenClaw session
4. run `analyze-task`
5. run `repo.prepare_workspace`
6. run `executor.run_coding_task`
7. run `repo.run_checks`
8. run `vcs.commit_and_push`
9. run `pr.create`
10. post chat and task updates
11. transition to `awaiting_ci` or `awaiting_review`

### Flow 2: `pr-feedback`

Purpose:

- continue an existing run after review comments

Steps:

1. resolve `pr_id -> run_id`
2. resume session
3. collect unresolved review comments
4. run `fix-pr-feedback`
5. rerun checks
6. push updates
7. reply in PR and chat

### Flow 3: `ci-recovery`

Purpose:

- recover from failed validation or deployment checks

Steps:

1. resolve `ci_run_id -> run_id`
2. fetch failure summary
3. decide patch vs escalate
4. if patch:
   - run `recover-ci-failure`
   - rerun checks
   - push update
5. otherwise move to `awaiting_human`

### Flow 4: `chat-command`

Purpose:

- allow a person to steer an in-flight run

Supported commands:

- `continue`
- `pause`
- `stop`
- `explain`
- `retry`
- `handoff`

## Skill Design

### `analyze-task`

Input:

- normalized task metadata
- full task body
- current repository context

Output:

- structured execution plan
- impacted files or modules
- missing information list
- risk level

### `implement-task`

Input:

- plan output
- workspace path
- repository policies

Output:

- code changes
- test/check summary
- commit summary

### `fix-pr-feedback`

Input:

- current diff
- unresolved comments
- failing checks if any

Output:

- patch summary
- addressed comments
- unresolved blockers

### `recover-ci-failure`

Input:

- CI failure summary
- latest code state

Output:

- retry decision
- patch or escalation summary

## Executor Contract

The executor contract should stay generic even if Codex is the only initial backend.

Input shape:

```json
{
  "workspace_path": "/path/to/workspace",
  "task_prompt": "Implement task AB#12345",
  "constraints": [
    "use existing patterns",
    "run tests before finishing",
    "do not merge"
  ],
  "artifacts": {
    "task": {},
    "plan": {},
    "repo_context": {}
  }
}
```

Output shape:

```json
{
  "status": "completed",
  "summary": "Patched validation and added tests",
  "changed_files": [
    "src/foo.ts",
    "tests/foo.test.ts"
  ],
  "checks": [
    {
      "name": "unit",
      "status": "passed"
    }
  ],
  "follow_up": []
}
```

## Provider Configuration Model

Keep provider config external and environment-driven.

Example:

```yaml
providers:
  task_pr:
    mode: ado-rest
    base_url: https://ado.internal.local
    project: MyProject
    auth:
      type: pat
      secret_env: ADO_PAT

  chat:
    mode: rocketchat-webhook
    base_url: https://chat.internal.local
    room: ai-dev
    auth:
      type: token
      secret_env: RC_TOKEN

  executor:
    mode: codex-acp
    harness: codex
    backend: acpx
```

## Deployment Design

### Shared Files

```text
deploy/
  config/
    openclaw.json
    providers.yaml
    harness-policy.yaml
  docker/
    compose.yml
    .env.example
  systemd/
    openclaw.service
    harness-bridge.service
  windows/
    install-openclaw.ps1
    install-harness-service.ps1
  scripts/
    healthcheck.sh
    healthcheck.ps1
```

### Docker Mode

Recommended services:

```text
openclaw
harness-bridge        # only if needed by the chosen webhook implementation
bot-review            # optional
rocketchat            # optional
```

Notes:

- keep Azure DevOps Server outside the compose stack
- keep SQLite on a mounted volume
- keep plugin artifacts local and version-pinned

### Non-Docker Mode

Install flow:

1. install OpenClaw
2. run `openclaw onboard --install-daemon`
3. install harness plugin bundle from local artifact
4. place config under the chosen config root
5. if bridge process is needed, install it as:
   - `systemd` on Linux
   - Windows service wrapper on Windows

## Security and Policy

### Minimum policy set

- no direct pushes to protected branches
- PR creation allowed
- merge not allowed in v1
- write-capable executor only for approved repositories
- dangerous shell/file permissions only for execution agents
- admin UI restricted to operators

### Secret handling

- all provider secrets from environment or secret files
- no secrets embedded in skill definitions
- separate service identities for:
  - task/PR provider
  - chat provider
  - coding executor

## Monitoring

Minimum metrics:

- runs started
- runs completed
- runs failed
- average time to PR
- CI recovery success rate
- duplicate-event suppression count
- lock contention count
- executor failure count

Minimum health endpoints if a bridge process exists:

- `/healthz`
- `/readyz`

CLI health checks:

- `openclaw gateway status`
- `openclaw flows list`
- `openclaw tasks list`

## MVP Cut Line

### Build now

- single OpenClaw Gateway
- Codex via ACP
- Azure DevOps task + PR + CI integration
- Rocket.Chat notify-only integration
- local runtime store with SQLite
- task-run, pr-feedback, ci-recovery flows
- Docker and non-Docker installation bundles

### Delay until later

- full two-way Rocket.Chat conversational control
- multi-gateway clustering
- PostgreSQL migration
- auto-merge after approvals
- advanced approval console
- multi-provider simultaneous production support

## Acceptance Criteria

1. A new eligible Azure DevOps task can create a `TaskRun`.
2. OpenClaw can generate a structured plan from that task.
3. OpenClaw can invoke Codex via ACP and obtain code changes.
4. The system can create a branch and PR in the configured repository.
5. A PR comment can resume the same run and apply a follow-up patch.
6. A CI failure can resume the same run and either patch or escalate.
7. Rocket.Chat can receive task and PR lifecycle notifications.
8. The same bundle can be deployed through Docker and native service install.

## Implementation Sequence

1. Build provider-neutral runtime store and status model.
2. Implement Azure DevOps adapter in `ado-rest` mode first.
3. Register Codex ACP executor and test workspace execution.
4. Implement `analyze-task` and `implement-task`.
5. Implement `task-run` flow end-to-end.
6. Add PR feedback and CI recovery flows.
7. Add Rocket.Chat notifications.
8. Add Docker and native installers.
9. Validate whether official Azure DevOps MCP can replace part of the custom adapter.

## Open Questions

- Is the target deployment Azure DevOps Services or Azure DevOps Server?
- Does the first release require threaded Rocket.Chat commands, or are notifications enough?
- Should the bridge/handler stay embedded in the plugin or be broken into a tiny companion process on day one?
- Does the first release need a human approval gate before PR creation for certain repositories?
