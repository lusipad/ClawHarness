# ClawHarness Architecture

Superseded by: `.omx/plans/clawharness-master-plan-2026-04-05.md`

Date: 2026-04-05
Status: Draft baseline architecture
Scope: Internal-network deployment with pluggable DevOps, chat, and coding executors

## Requirements Summary

Build an internal AI software harness that can:

- take work from a DevOps/task system such as Azure DevOps
- let an AI employee analyze and plan the work
- execute coding changes through a switchable coding harness such as Codex CLI
- communicate through a switchable chat channel such as Rocket.Chat
- open PRs, react to review and CI feedback, and continue iterating
- deploy quickly in both Docker and non-Docker environments
- stay provider-neutral enough to swap DevOps, chat, and coding backends later

## Non-Goals

- building a new general-purpose agent platform from scratch
- replacing the source-of-truth roles of DevOps, Git hosting, PR, or CI systems
- full enterprise IAM/SSO unification in the first release
- multi-tenant SaaS architecture

## Design Principles

1. OpenClaw is the AI control plane.
2. Provider-specific APIs stay behind plugins, MCP tools, or adapters.
3. Reliability logic stays thin and explicit instead of hiding inside prompts.
4. Skills expose stable business capabilities, not vendor-branded commands.
5. The deployment package must support both Docker and native service installs.
6. The system should degrade gracefully when a provider is swapped.

## ADR

### Decision

Use `OpenClaw Gateway + TaskFlow + ACP + plugins/skills/MCP` as the primary orchestration base, with only a thin sidecar for external event intake, run mapping, locking, and audit logging.

### Drivers

- OpenClaw already provides channels, sessions, routing, plugins, TaskFlow, hooks, and ACP.
- The user wants executor, chat, and DevOps providers to remain swappable.
- The deployment needs to stay lightweight enough for internal-network rollout.
- Codex CLI can execute coding work directly, but it does not replace run-state management.

### Alternatives Considered

- Build a standalone orchestrator first:
  Rejected because it would duplicate OpenClaw workflow, routing, and session capabilities.
- Make Codex CLI the center and keep OpenClaw optional:
  Rejected because it weakens multi-channel, multi-executor, and long-lived agent-session handling.
- Build only provider-specific scripts without a runtime layer:
  Rejected because webhook dedupe, retry, locks, and audit would become brittle.

### Why Chosen

This choice keeps the center of gravity in the product that already models channels, sessions, and agent workflows, while keeping the custom code limited to the reliability and provider-integration seams that are still missing.

### Consequences

- Most custom work moves into OpenClaw plugins, skills, MCP registration, and one small sidecar.
- The architecture remains portable across Azure DevOps, Jira, GitHub, GitLab, Rocket.Chat, Slack, Teams, Codex, Claude Code, and other supported providers.
- Azure DevOps Services can likely reuse the official Microsoft MCP server faster than Azure DevOps Server on-prem.

### Follow-ups

- Validate whether the target environment is Azure DevOps Services or Azure DevOps Server.
- Decide whether Rocket.Chat starts as a webhook bridge or a maintained channel plugin fork.
- Decide whether first release needs only single-agent execution or multi-agent review loops.

## Reference Inputs

- OpenClaw overview and gateway positioning: <https://docs.openclaw.ai/>
- OpenClaw channels: <https://docs.openclaw.ai/channels/index>
- OpenClaw plugins: <https://docs.openclaw.ai/plugins>
- OpenClaw automation and hooks: <https://docs.openclaw.ai/automation/>
- OpenClaw background tasks: <https://docs.openclaw.ai/automation/tasks>
- OpenClaw TaskFlow: <https://docs.openclaw.ai/automation/taskflow>
- OpenClaw ACP agents: <https://docs.openclaw.ai/tools/acp-agents>
- OpenClaw ACP CLI: <https://docs.openclaw.ai/cli/acp>
- Microsoft Azure DevOps MCP Server: <https://github.com/microsoft/azure-devops-mcp>
- Azure DevOps MCP toolset: <https://github.com/microsoft/azure-devops-mcp/blob/main/docs/TOOLSET.md>
- Azure DevOps single-server install: <https://learn.microsoft.com/en-us/azure/devops/server/install/single-server?view=azure-devops-2022>
- Azure DevOps Server requirements: <https://learn.microsoft.com/en-us/azure/devops/server/requirements?view=azure-devops-2022>
- Rocket.Chat Docker Compose deployment: <https://docs.rocket.chat/docs/deploy-with-docker-docker-compose>
- Rocket.Chat integrations: <https://docs.rocket.chat/docs/integrations>
- OpenAI Symphony architecture reference: <https://github.com/openai/symphony>

## High-Level Architecture

```text
                        +---------------------------+
                        |    DevOps Provider(s)     |
                        | ADO / GitHub / GitLab     |
                        | Jira / Linear / Jenkins   |
                        +-------------+-------------+
                                      |
                           MCP / adapter plugins
                                      |
                        +-------------v-------------+
                        |       OpenClaw Gateway    |
                        |---------------------------|
                        | Sessions / Routing        |
                        | Channels                  |
                        | TaskFlow / Hooks / Tasks  |
                        | Skills / MCP tool calls   |
                        | ACP executor dispatch     |
                        +------+------+-------------+
                               |      |
                channel plugin |      | ACP
                               |      |
                    +----------v--+   +----------------------+
                    | Chat tools  |   | Coding executors     |
                    | Rocket.Chat |   | Codex / Claude / ... |
                    | Slack/Teams |   +----------------------+
                    +-------------+
                               ^
                               |
                       webhook / thread bridge
                               |
                    +----------+----------+
                    | Thin Reliability    |
                    | Sidecar             |
                    |---------------------|
                    | Event intake        |
                    | Run registry        |
                    | Locks / idempotency |
                    | Retry / audit       |
                    +---------------------+
```

## Core Component Model

### 1. OpenClaw Gateway

OpenClaw is the control plane and should own:

- user and AI conversations
- channel routing
- agent sessions
- task planning and multi-step execution
- tool invocation through plugins, MCP, and ACP
- background task state for long-running work

OpenClaw should not become the sole external-system ledger. DevOps systems remain the truth for work items, code, PRs, and CI status.

### 2. Provider Plugins and Skills

Most business actions should be exposed as OpenClaw-callable capabilities.

Preferred capability names:

- `task.list_candidates`
- `task.get`
- `task.update_status`
- `task.add_comment`
- `repo.prepare_workspace`
- `repo.read_context`
- `repo.run_checks`
- `vcs.create_branch`
- `vcs.commit_and_push`
- `pr.create`
- `pr.get`
- `pr.list_comments`
- `pr.reply`
- `ci.get_status`
- `ci.retry`
- `chat.post_update`
- `chat.read_thread`
- `executor.run_coding_task`

These should map to provider-specific implementations behind the scenes.

### 3. ACP Executor Layer

OpenClaw should use ACP to dispatch coding execution to switchable harnesses:

- Codex CLI first
- Claude Code later if needed
- Gemini CLI or another ACP-capable executor later

The AI employee plans with OpenClaw but may delegate file-changing execution to Codex.

### 4. Thin Reliability Sidecar

The sidecar is mandatory but intentionally small.

Responsibilities:

- receive inbound webhooks from DevOps or chat systems
- deduplicate repeated events
- map external object IDs to OpenClaw sessions and runs
- hold distributed or local locks so one task is not handled twice
- record run metadata and audit history
- apply retry and backoff rules

Non-responsibilities:

- planning
- code generation
- long-form reasoning
- provider-specific business logic that belongs in skills/plugins

### 5. Optional Admin UI

`OpenClaw-bot-review` or a forked equivalent is optional and should remain an operations panel, not the orchestration core.

## Capability Boundaries

### What should be an OpenClaw plugin

- channel integrations
- provider tool registration
- packaging of MCP-backed capabilities
- reusable skill definitions
- prompts, policies, and TaskFlow recipes

### What should be an MCP server

- broad DevOps capability surfaces
- Azure DevOps work item, PR, repo, and pipeline operations
- provider-neutral tool contracts when shared across agents

Use the official Azure DevOps MCP server first where supported. For Azure DevOps Server on-prem, expect to validate compatibility or maintain a fork/custom adapter.

### What should be a skill

- capability bundles the AI employee calls often
- plan-then-execute workflows
- review-fix workflows
- CI-failure triage workflows
- chat-summary and status-posting workflows

Example skills:

- `analyze-task`
- `implement-task`
- `fix-pr-feedback`
- `recover-from-ci-failure`
- `handoff-to-human`

### What must stay in the sidecar/runtime layer

- event listener endpoints
- dedupe stores
- run registry
- lock management
- retries and dead-letter handling
- audit trails

## Logical Data Model

The system needs a provider-neutral run model.

```text
TaskRun
- run_id
- provider_type
- task_id
- repository_id
- workspace_path
- branch_name
- pr_id
- ci_run_id
- chat_thread_id
- openclaw_session_id
- executor_type
- status
- retry_count
- last_error
- started_at
- updated_at
```

Recommended statuses:

- `queued`
- `claimed`
- `planning`
- `coding`
- `awaiting_pr`
- `awaiting_ci`
- `awaiting_human`
- `retrying`
- `completed`
- `failed`
- `cancelled`

## Primary Runtime Flows

### Flow A: New Task to PR

1. DevOps system emits a new-task event or the sidecar poller finds an eligible task.
2. Sidecar acquires the task lock and creates or resumes a `TaskRun`.
3. Sidecar starts or resumes the mapped OpenClaw session.
4. OpenClaw runs `analyze-task`.
5. OpenClaw prepares workspace context via `repo.prepare_workspace`.
6. OpenClaw dispatches coding work to Codex through ACP.
7. OpenClaw runs verification skills.
8. OpenClaw calls `vcs.commit_and_push` and `pr.create`.
9. OpenClaw posts status back to task and chat.
10. Sidecar records final state and waits for PR/CI follow-up events.

### Flow B: PR Review Feedback

1. PR comment event arrives.
2. Sidecar maps `pr_id -> TaskRun -> OpenClaw session`.
3. OpenClaw runs `fix-pr-feedback`.
4. Codex applies changes.
5. Verification reruns.
6. OpenClaw responds in PR and optionally chat.

### Flow C: CI Failure Recovery

1. CI failure event arrives.
2. Sidecar maps `ci_run_id -> TaskRun`.
3. OpenClaw reads logs or summaries through provider tools.
4. OpenClaw decides whether to retry, patch, or escalate.
5. Codex makes fixes if needed.
6. OpenClaw triggers or waits for CI rerun and updates status.

### Flow D: Chat Intervention

1. User replies in the mapped chat thread.
2. Channel plugin or bridge resolves the message to the OpenClaw session.
3. OpenClaw interprets intent:
   - continue
   - pause
   - explain
   - retry
   - stop
4. Sidecar writes any state transition that must outlive the session.

## Deployment Architecture

### Deployment Objective

Ship the same core artifacts into both Docker and non-Docker environments.

### Shared Artifacts

- OpenClaw config templates
- plugin packages (`.tgz` or local directories)
- skill bundles
- sidecar app/binary
- environment templates
- health-check scripts

### Docker Mode

Recommended for fast pilots and repeatable setup.

Suggested services:

- `openclaw`
- `harness-sidecar`
- optional `bot-review`
- optional `rocketchat`
- optional provider-local MCP containers if supported

Example target layout:

```text
docker compose
  openclaw
  harness-sidecar
  bot-review            # optional
  rocketchat            # optional
```

Keep Azure DevOps Server outside this compose stack.

### Non-Docker Mode

Recommended for locked-down internal environments.

Suggested service wrappers:

- Linux: `systemd`
- Windows: service wrapper such as NSSM or native service host

Install pattern:

1. install OpenClaw natively
2. install plugin packages from local artifacts
3. run sidecar as a native service
4. register channel/provider config

### Production Internal Topology

Small rollout:

- `Host A`: OpenClaw + sidecar
- `Host B`: Azure DevOps Server
- `Host C`: Rocket.Chat if needed

Moderate rollout:

- `Host A`: OpenClaw Gateway
- `Host B`: sidecar + MCP adapters
- `Host C`: Rocket.Chat + Mongo
- `Host D`: Azure DevOps Server + SQL
- `Host E+`: worker hosts for heavy coding execution

## Packaging and Repository Strategy

Recommended repository split:

```text
harness/
  plugins/
    chat-provider/
    devops-provider/
    executor-tools/
  skills/
    analyze-task/
    implement-task/
    fix-pr-feedback/
    recover-from-ci-failure/
  sidecar/
    src/
    config/
  deploy/
    docker/
    systemd/
    windows/
    scripts/
  docs/
    architecture/
    runbooks/
```

Release artifacts:

- `openclaw-plugin-<name>-<version>.tgz`
- `skills-bundle-<version>.zip` or directory package
- `harness-sidecar-<version>`
- `deploy-bundle-<version>.zip`

## Security Architecture

### Identity and Access

- use dedicated service accounts for DevOps, chat, and executor access
- prefer PAT/token auth over shared username/password where supported
- keep tokens scoped to minimal required permissions
- keep human access and AI service access separate

### Workspace Isolation

- one repository workspace per active task run
- no shared mutable workspace across concurrent runs
- branch-per-run or branch-per-task
- explicit cleanup and archival policy

### Execution Controls

- default-deny dangerous skills
- separate read-only planning agents from write-capable implementation agents if needed
- require PR-based merge flow; no direct writes to protected branches
- add policy gates for high-risk repositories or paths

### Data Protection

- treat OpenClaw session and transcript storage as sensitive
- restrict bot-review or admin UI to administrators only
- centralize audit logs for:
  - task claims
  - code-writing runs
  - PR creation
  - retries
  - human overrides

## Observability and Operations

Minimum required telemetry:

- task run counts by status
- average time from claim to PR
- retry counts
- PR reopen rate
- CI failure recovery success rate
- executor failure rate
- channel delivery failures

Minimum operational runbooks:

- token rotation
- failed run replay
- webhook dead-letter reprocessing
- stuck lock cleanup
- workspace cleanup
- plugin rollback

Backups:

- OpenClaw config and session storage
- sidecar run registry and audit store
- chat configuration if self-hosted
- Azure DevOps backup according to official guidance

## Recommended First Release Scope

### In Scope

- OpenClaw as control plane
- Codex CLI via ACP
- Azure DevOps provider tools
- one chat path for notifications and optional thread replies
- sidecar with webhook intake, run registry, lock, audit
- Docker and non-Docker deployment support

### Out of Scope

- multi-tenant control plane
- advanced approval UI
- generalized marketplace of providers
- autonomous merge-to-main without branch policy gates
- large-scale multi-agent specialization

## MVP Acceptance Criteria

- a new eligible task can trigger a single AI work run end-to-end
- the AI employee can analyze the task and produce a visible plan
- the system can modify code via a switchable coding executor
- the system can push a branch and create a PR
- PR and CI follow-up can resume the same run context
- status can be posted to at least one chat provider
- the deployment bundle can run in Docker and non-Docker modes
- one provider can be swapped in each of these categories with no workflow rewrite:
  - chat
  - coding executor
  - task/PR provider

## Implementation Steps

1. Establish the provider-neutral capability contract.
   Deliverables:
   - capability names and payload schemas
   - sidecar run model
   - OpenClaw skill naming convention

2. Stand up OpenClaw with ACP and baseline skills.
   Deliverables:
   - OpenClaw runtime config
   - Codex executor registration through ACP
   - initial TaskFlow definitions

3. Integrate the DevOps provider.
   Deliverables:
   - Azure DevOps MCP adoption or custom adapter
   - work item, repo, PR, and CI tool coverage
   - provider configuration templates

4. Build the thin reliability sidecar.
   Deliverables:
   - webhook endpoints
   - lock and dedupe
   - run registry
   - audit log

5. Add chat delivery and optional thread binding.
   Deliverables:
   - Rocket.Chat webhook or channel plugin path
   - chat thread to run mapping
   - status message templates

6. Package both deployment modes.
   Deliverables:
   - Docker Compose bundle
   - native-service bundle
   - install scripts
   - health checks

7. Verify with realistic end-to-end scenarios.
   Deliverables:
   - new task -> PR
   - PR feedback -> patch
   - CI failure -> retry/fix
   - chat stop/continue

## Risks and Mitigations

- Azure DevOps Server compatibility with the official Azure DevOps MCP server may be incomplete.
  Mitigation:
  - validate early against the target deployment type
  - keep a fallback custom adapter or fork path

- Rocket.Chat channel support may rely on community-maintained integration.
  Mitigation:
  - start with webhook notifications
  - move to a maintained plugin fork only after proving demand for richer chat control

- Long-running AI sessions can drift or lose context.
  Mitigation:
  - persist task run metadata outside the session
  - keep run state in the sidecar
  - use resumable TaskFlow patterns

- Shared workspaces can corrupt concurrent runs.
  Mitigation:
  - use per-task or per-run workspaces
  - enforce lock ownership

- Over-abstracting too early can slow delivery.
  Mitigation:
  - keep only three provider seams in v1:
    - task/pr provider
    - chat provider
    - code executor

## Verification Steps

1. Validate OpenClaw deployment in Docker and native modes.
2. Validate ACP executor handoff to Codex.
3. Validate provider tool coverage for:
   - read task
   - update task
   - create branch
   - create PR
   - read CI status
4. Validate webhook dedupe by replaying the same event multiple times.
5. Validate task locking by issuing concurrent start attempts.
6. Validate PR comment and CI failure recovery loops.
7. Validate chat notifications and thread mapping.
8. Validate token rotation and plugin rollback runbooks.

## Recommended Immediate Next Step

Move from architecture to a narrower MVP technical design with:

- exact capability schemas
- sidecar storage choice
- OpenClaw TaskFlow definitions
- Docker and native service packaging layout
- Azure DevOps Services vs Server compatibility decision
