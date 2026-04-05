# ClawHarness Support Matrix and Provider Configuration

Superseded by: `.omx/plans/clawharness-master-plan-2026-04-05.md`

Date: 2026-04-05
Status: Support matrix baseline
Depends on:
- `.omx/plans/clawharness-architecture-2026-04-05.md`
- `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md`

## Purpose

Define how the harness supports:

- Azure DevOps Services and Azure DevOps Server
- Docker and non-Docker deployments
- multiple chat integration modes
- multiple coding executors

The key rule is:

**one workflow model, multiple provider modes**

OpenClaw flows and skills must not fork by vendor. Only provider adapters change.

## Support Dimensions

The platform has four interchangeable seams:

1. Task/PR/CI provider
2. Chat provider
3. Coding executor
4. Runtime packaging

## Unified Capability Contract

All provider modes must implement the same internal capability set.

### Task and planning capabilities

- `task.list_candidates`
- `task.get`
- `task.update_status`
- `task.add_comment`

### Repository and code capabilities

- `repo.prepare_workspace`
- `repo.read_context`
- `repo.run_checks`
- `vcs.create_branch`
- `vcs.commit_and_push`

### Pull request capabilities

- `pr.create`
- `pr.get`
- `pr.list_comments`
- `pr.reply`

### CI capabilities

- `ci.get_status`
- `ci.retry`

### Chat capabilities

- `chat.post_update`
- `chat.post_error`
- `chat.read_thread`
- `chat.resolve_thread_target`

### Executor capabilities

- `executor.run_coding_task`
- `executor.resume_coding_task`
- `executor.cancel_coding_task`

## Provider Modes

### Task/PR/CI provider modes

#### `ado-rest`

Purpose:

- baseline provider mode
- mandatory first implementation
- supports Azure DevOps Server and Azure DevOps Services

Backends:

- Azure DevOps REST APIs
- Service Hooks for inbound events
- branch policies and CI pipelines left in native Azure DevOps control

Use when:

- the environment is Azure DevOps Server
- MCP coverage is incomplete
- you need predictable control over API behavior

#### `ado-mcp`

Purpose:

- accelerated provider mode for Azure DevOps Services
- optional overlay on top of `ado-rest`

Backends:

- official Microsoft Azure DevOps MCP Server where compatible

Use when:

- the environment is Azure DevOps Services
- official MCP server covers required operations

Rule:

- `ado-mcp` must be optional, never mandatory for core workflow
- if `ado-mcp` fails or lacks coverage, the system falls back to `ado-rest`

### Chat provider modes

#### `rocketchat-webhook`

Purpose:

- default MVP mode
- notify-only messaging

Capabilities implemented:

- `chat.post_update`
- `chat.post_error`

Not implemented by default:

- full thread reading
- command ingestion

Use when:

- the team only needs notifications
- rapid deployment matters more than conversational control

#### `rocketchat-bridge`

Purpose:

- advanced mode for session-aware thread mapping and commands

Capabilities implemented:

- `chat.post_update`
- `chat.post_error`
- `chat.read_thread`
- `chat.resolve_thread_target`

Use when:

- human steering from Rocket.Chat is required
- thread-to-run mapping must be first-class

### Executor modes

#### `codex-acp`

Purpose:

- default coding executor mode

Backend:

- OpenClaw ACP -> Codex

Use when:

- running the primary MVP

#### Future executor modes

- `claude-acp`
- `gemini-acp`
- `custom-acp`

Rule:

- no workflow changes when switching executors
- only provider config and executor adapter change

### Packaging modes

#### `docker`

Purpose:

- fastest install
- repeatable pilot setup

#### `native`

Purpose:

- locked-down internal environments
- service-managed production installs

## Support Matrix

### Task/PR/CI provider matrix

| Provider mode | Azure DevOps Services | Azure DevOps Server | MVP priority | Notes |
| --- | --- | --- | --- | --- |
| `ado-rest` | Yes | Yes | P0 | Required base path |
| `ado-mcp` | Yes | Validate first | P1 | Optional accelerator |

Interpretation:

- `ado-rest` is the guaranteed compatibility layer
- `ado-mcp` is an optimization layer, not a dependency

### Chat matrix

| Chat mode | Docker | Native | MVP priority | Notes |
| --- | --- | --- | --- | --- |
| `rocketchat-webhook` | Yes | Yes | P0 | Start here |
| `rocketchat-bridge` | Yes | Yes | P1 | Add after core flow stabilizes |

### Executor matrix

| Executor mode | Docker | Native | MVP priority | Notes |
| --- | --- | --- | --- | --- |
| `codex-acp` | Yes | Yes | P0 | Primary executor |
| `claude-acp` | Future | Future | P2 | Design for it now, implement later |
| `gemini-acp` | Future | Future | P2 | Design for it now, implement later |

### Packaging matrix

| Packaging mode | OpenClaw | Runtime store | Chat notify | ADO provider | MVP priority |
| --- | --- | --- | --- | --- | --- |
| `docker` | containerized | mounted SQLite | yes | yes | P0 |
| `native` | system install | local SQLite | yes | yes | P0 |

## Recommended Implementation Order

### Phase 1

- `ado-rest`
- `rocketchat-webhook`
- `codex-acp`
- `docker`
- `native`

This is the only required MVP set.

### Phase 2

- `ado-mcp` overlay for Azure DevOps Services
- `rocketchat-bridge`

### Phase 3

- alternate ACP executors
- PostgreSQL runtime store
- multi-gateway coordination

## Configuration Design

Use one provider configuration file with explicit mode selection.

Suggested file:

```text
deploy/config/providers.yaml
```

### Example full configuration

```yaml
providers:
  task_pr_ci:
    family: azure-devops
    mode: ado-rest
    fallback_mode: ado-rest
    base_url: https://ado.internal.local
    project: MyProject
    organization: null
    auth:
      type: pat
      secret_env: ADO_PAT
    events:
      mode: webhook
      webhook_secret_env: ADO_WEBHOOK_SECRET

  chat:
    family: rocketchat
    mode: rocketchat-webhook
    base_url: https://chat.internal.local
    room: ai-dev
    auth:
      type: token
      secret_env: RC_TOKEN

  executor:
    family: acp
    mode: codex-acp
    harness: codex
    backend: acpx
    runtime:
      mode: persistent
      timeout_seconds: 3600

runtime:
  storage:
    kind: sqlite
    path: ~/.openclaw/harness/harness.db
  workspace_root: ~/.openclaw/workspace/harness
  branch_prefix: ai
  lock_ttl_seconds: 1800
  dedupe_ttl_seconds: 86400
  audit_retention_days: 30
```

### Example Azure DevOps Services profile

```yaml
providers:
  task_pr_ci:
    family: azure-devops
    mode: ado-mcp
    fallback_mode: ado-rest
    organization: my-org
    project: MyProject
    base_url: https://dev.azure.com/my-org
    auth:
      type: oauth-or-pat
      secret_env: ADO_PAT
```

### Example Azure DevOps Server profile

```yaml
providers:
  task_pr_ci:
    family: azure-devops
    mode: ado-rest
    fallback_mode: ado-rest
    base_url: https://ado-server.internal.local/tfs
    project: MyCollection/MyProject
    auth:
      type: pat
      secret_env: ADO_PAT
```

## Runtime Selection Rules

The harness runtime should resolve provider behavior in this order:

1. load selected mode from config
2. verify mode prerequisites
3. if prerequisites fail and `fallback_mode` exists, fall back
4. emit audit event when fallback occurs
5. continue without changing skill contracts

Example:

- configured mode: `ado-mcp`
- official MCP server unavailable or unsupported
- runtime falls back to `ado-rest`
- TaskFlow continues unchanged

## Workflow Stability Rule

OpenClaw flows must only call unified capabilities.

Allowed:

- `task.get`
- `pr.create`
- `ci.get_status`
- `chat.post_update`
- `executor.run_coding_task`

Not allowed in shared flows:

- `ado.create_pr`
- `rocketchat.send_message`
- `codex.exec`

Vendor-specific calls belong only inside adapters.

## Deployment Profiles

### Profile A: Fast Pilot

Use:

- `docker`
- `ado-rest`
- `rocketchat-webhook`
- `codex-acp`

Best for:

- POC
- one internal team
- fastest rollout

### Profile B: Internal Production Starter

Use:

- `native` or `docker`
- `ado-rest`
- `rocketchat-webhook`
- `codex-acp`

Add:

- stricter policies
- backup jobs
- health checks
- service supervision

### Profile C: Azure DevOps Services Optimized

Use:

- `docker` or `native`
- `ado-mcp` with `ado-rest` fallback
- `rocketchat-webhook`
- `codex-acp`

Best for:

- cloud-hosted ADO organizations
- teams that want faster provider integration through MCP

## What Not to Build

Do not build:

- separate workflows for Services and Server
- separate workflows for Docker and native
- executor-specific flows
- a second chat abstraction outside the provider adapter layer
- a custom MCP-like protocol for provider access

## Validation Matrix

Before claiming support, verify each profile:

### ADO Services validation

- read task
- update task
- create branch
- create PR
- read CI status
- PR comment resume

### ADO Server validation

- read task
- update task
- create branch
- create PR
- read CI status
- webhook intake

### Docker validation

- mounted SQLite persistence survives restart
- plugin bundle installs from local artifact
- Codex ACP executor can reach workspace
- chat notifications deliver

### Native validation

- OpenClaw daemon survives reboot
- runtime store path permissions are correct
- service wrapper starts cleanly
- webhook listener is reachable

## Acceptance Criteria

1. One OpenClaw TaskFlow works unchanged against both `ado-rest` profiles:
   - Azure DevOps Services
   - Azure DevOps Server
2. The same plugin bundle works in both:
   - Docker deployment
   - native service deployment
3. The same flow works with:
   - `rocketchat-webhook`
   - `rocketchat-bridge` later
4. Executor replacement does not require flow edits.

## Recommended Next Step

Move from matrix design to implementation artifacts:

1. define exact JSON schemas for each unified capability
2. create `providers.yaml` template
3. stub `ado-rest` adapter first
4. stub `codex-acp` executor adapter
5. create `task-run` TaskFlow using only unified capabilities
