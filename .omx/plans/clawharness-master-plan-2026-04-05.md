# ClawHarness Master Plan

Date: 2026-04-05
Status: Canonical integrated plan
Supersedes:
- `.omx/plans/clawharness-architecture-2026-04-05.md`
- `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md`
- `.omx/plans/clawharness-support-matrix-2026-04-05.md`

## Goal

Build an internal AI software harness that:

- takes work from Azure DevOps
- lets OpenClaw analyze and plan the work
- uses Codex through ACP to make code changes
- opens a PR
- reacts to PR comments and CI failures
- sends status updates to Rocket.Chat
- can be deployed with Docker or without Docker

## KISS Decisions

These decisions are fixed for v1.

- `OpenClaw` is the center.
- `Codex` is used through existing `ACP` support.
- `Azure DevOps` integration starts with `REST`, not MCP.
- `Rocket.Chat` starts with `webhook notifications`, not a full chat bridge.
- `SQLite` is the only runtime store in v1.
- One `OpenClaw Gateway` instance is enough for v1.
- One workspace is created per task run.
- No auto-merge in v1.
- No multi-provider runtime in v1.
- No heavy external orchestrator in v1.

## What We Are Not Building

- a new general-purpose agent platform
- a full provider marketplace
- a complex workflow engine outside OpenClaw
- a second chat abstraction layer
- a second executor abstraction layer beyond what ACP already gives us
- separate flows for Azure DevOps Services and Azure DevOps Server

## Final Shape

```text
Azure DevOps
  -> webhook or poll
  -> OpenClaw hook
  -> task-run flow
  -> OpenClaw planning
  -> Codex via ACP
  -> git push + PR
  -> Rocket.Chat webhook notify
```

If OpenClaw's installed webhook/hook surface is enough, everything stays inside the plugin bundle.

If it is not enough, add one tiny companion process only for:

- receiving webhooks
- writing to SQLite
- waking OpenClaw

That process is not a full orchestrator.

## Core Components

### 1. OpenClaw

OpenClaw owns:

- sessions
- planning
- flows
- hooks
- task continuation
- executor dispatch through ACP

OpenClaw does not replace Azure DevOps as the source of truth for tasks, PRs, or CI.

### 2. Codex via ACP

Codex is the coding worker.

OpenClaw decides when to call it.
ACP is already the transport. We do not build a custom Codex protocol.

### 3. Azure DevOps client

This is a small concrete module, not a generic provider framework.

It handles:

- get task
- update task
- add task comment
- create branch if needed
- push branch
- create PR
- read PR comments
- read CI status
- retry CI if allowed

Support rule:

- `Azure DevOps REST` first
- later optionally add `MCP` behind the same call sites if it proves useful

### 4. Rocket.Chat notifier

This is a small notifier module.

It handles:

- post task started
- post PR opened
- post CI failed
- post task completed
- post task blocked

It does not need to be conversational in v1.

### 5. Runtime store

Use `SQLite`.

It stores:

- runs
- locks
- dedupe fingerprints
- PR mapping
- CI mapping
- chat thread mapping if needed later
- audit events

## Minimal Modules

Do not build more modules than these until duplication appears.

```text
harness/
  openclaw-plugin/
    flows/
    hooks/
    skills/
    runtime/
  ado_client/
  codex_acp_runner/
  rocketchat_notifier/
  run_store/
  deploy/
```

Concrete responsibility split:

- `ado_client`
  - only Azure DevOps REST calls
- `codex_acp_runner`
  - only Codex execution through OpenClaw ACP
- `rocketchat_notifier`
  - only Rocket.Chat notifications
- `run_store`
  - only SQLite persistence and locks
- `openclaw-plugin`
  - flows, hooks, skills, and composition

## Main Flow

### Task to PR

1. Azure DevOps emits a task event or a poller finds an eligible task.
2. The task is normalized into a run record.
3. A lock is acquired for that task.
4. OpenClaw starts or resumes a session for the run.
5. OpenClaw runs `analyze-task`.
6. OpenClaw prepares the workspace.
7. OpenClaw calls Codex through ACP.
8. Checks run.
9. Branch is pushed.
10. PR is created.
11. Rocket.Chat gets a notification.
12. Run status becomes `awaiting_ci` or `awaiting_review`.

### PR Feedback

1. PR comment event arrives.
2. PR is mapped back to the run.
3. OpenClaw resumes the same session.
4. OpenClaw runs `fix-pr-feedback`.
5. Codex makes the patch.
6. Checks rerun.
7. Update is pushed.
8. Rocket.Chat gets a notification.

### CI Failure

1. CI failure event arrives.
2. CI run is mapped back to the task run.
3. OpenClaw reads the failure summary.
4. OpenClaw decides:
   - patch and retry
   - or block and hand off to human
5. Rocket.Chat gets a notification.

## Statuses

Keep the status list short.

- `queued`
- `claimed`
- `planning`
- `coding`
- `opening_pr`
- `awaiting_ci`
- `awaiting_review`
- `awaiting_human`
- `completed`
- `failed`
- `cancelled`

Add more only if a real workflow needs them.

## Data We Need

Only store what is necessary to resume work.

### `task_runs`

- `run_id`
- `task_id`
- `task_key`
- `repo_id`
- `workspace_path`
- `branch_name`
- `pr_id`
- `ci_run_id`
- `session_id`
- `status`
- `retry_count`
- `last_error`
- `started_at`
- `updated_at`

### `task_locks`

- `lock_key`
- `run_id`
- `acquired_at`
- `expires_at`

### `event_dedupe`

- `fingerprint`
- `source_type`
- `source_id`
- `received_at`
- `expires_at`

### `run_audit`

- `run_id`
- `event_type`
- `payload_json`
- `created_at`

## Skills We Actually Need

Only create these four first:

- `analyze-task`
- `implement-task`
- `fix-pr-feedback`
- `recover-ci-failure`

Keep skill names business-oriented.

Do not create vendor-specific shared skills like:

- `ado-create-pr`
- `codex-run`
- `rocketchat-send`

Those belong inside modules, not in reusable flow definitions.

## Config

Keep config external and small.

Suggested files:

```text
deploy/config/openclaw.json
deploy/config/providers.yaml
deploy/config/harness-policy.yaml
```

Minimal `providers.yaml`:

```yaml
azure_devops:
  base_url: https://ado.internal.local
  project: MyProject
  auth_env: ADO_PAT

rocketchat:
  webhook_url_env: RC_WEBHOOK_URL

codex:
  harness: codex
  backend: acpx
  mode: persistent

runtime:
  sqlite_path: ~/.openclaw/harness/harness.db
  workspace_root: ~/.openclaw/workspace/harness
  branch_prefix: ai
  lock_ttl_seconds: 1800
```

If Azure DevOps Services later uses MCP, add it as one config flag in the Azure DevOps module. Do not redesign the system for it now.

## Deployment

### Docker

Support this first because it is the fastest to roll out.

Services:

- `openclaw`
- optional `bridge` only if webhook handling cannot stay in-plugin
- optional `bot-review`
- optional `rocketchat`

Keep Azure DevOps Server outside the compose stack.

### Non-Docker

Support this in parallel.

- OpenClaw as a native install
- plugin bundle installed from a local artifact
- optional bridge as a small service
- SQLite on local disk

Use:

- `systemd` on Linux
- a Windows service wrapper on Windows

## Security Rules

Keep them simple and hard.

- no direct push to protected branches
- PR creation allowed
- merge denied in v1
- one workspace per run
- separate service tokens for ADO and Rocket.Chat
- restrict admin UI to operators
- keep OpenClaw session storage private

## Observability

Minimum signals only:

- runs started
- runs completed
- runs failed
- average time to PR
- CI recovery count
- duplicate event count
- lock contention count

## MVP Acceptance Criteria

1. An eligible Azure DevOps task creates one run.
2. OpenClaw can analyze the task and produce a plan.
3. OpenClaw can call Codex through ACP.
4. Code changes can be committed and pushed to a task branch.
5. A PR can be created.
6. PR comments can resume the same run.
7. CI failures can resume the same run.
8. Rocket.Chat receives lifecycle notifications.
9. The same bundle can run with Docker and without Docker.

## Build Order

1. `run_store`
2. `ado_client`
3. `codex_acp_runner`
4. `rocketchat_notifier`
5. `openclaw-plugin`
   - `analyze-task`
   - `implement-task`
   - `task-run` flow
6. PR feedback flow
7. CI recovery flow
8. Docker install bundle
9. native install bundle

## Future Work

Only do these after the main loop is stable.

- Azure DevOps MCP overlay
- Rocket.Chat threaded control
- alternate ACP executors
- PostgreSQL
- multi-gateway deployment
- merge automation

## Immediate Next Files

If implementation starts next, create only these:

- `deploy/config/providers.yaml`
- `run_store/schema.sql`
- `ado_client` request list
- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/skills/analyze-task`
- `openclaw-plugin/skills/implement-task`
