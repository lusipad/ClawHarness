# ClawHarness v1 PRD and Detailed Delivery Plan

Date: 2026-04-05
Status: Execution baseline
Expands:
- `.omx/plans/clawharness-master-plan-2026-04-05.md`
- `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md`
- `.omx/plans/clawharness-support-matrix-2026-04-05.md`

## Baseline Sources

- Goal, fixed v1 decisions, module boundaries, main flow, statuses, MVP acceptance, build order, and immediate-next files come from `.omx/plans/clawharness-master-plan-2026-04-05.md:10-426`.
- Provider modes, support matrix, workflow stability, runtime fallback rules, and validation profiles come from `.omx/plans/clawharness-support-matrix-2026-04-05.md:209-497`.
- TaskFlow details, skill contracts, executor contract, deployment layout, security policy, monitoring, and implementation sequence come from `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md:168-784`.

## Product Goal

Build the smallest internal AI software harness that can ingest Azure DevOps work, let OpenClaw analyze and plan it, execute code changes through Codex via ACP, open a PR, react to PR comments and CI failures, notify Rocket.Chat, and run in both Docker and native installs.

## Fixed v1 Decisions

These decisions are treated as locked unless a later ADR replaces them:

- OpenClaw is the control center.
- Codex is reached through ACP, not a custom executor protocol.
- Azure DevOps starts with `ado-rest`; `ado-mcp` is an optional later overlay.
- Rocket.Chat starts in `rocketchat-webhook` notify-only mode.
- SQLite is the only runtime store in v1.
- One OpenClaw Gateway instance is enough for v1.
- One workspace is created per task run.
- No auto-merge, no multi-provider runtime, and no heavy external orchestrator in v1.

## Assumptions for Detailed Planning

The current source plans leave three open questions: Azure DevOps Services vs Server, notify-only vs threaded Rocket.Chat, and embedded webhook handling vs tiny companion process. To avoid blocking execution, this plan uses the lowest-risk assumptions and converts the open questions into early validation gates:

- Baseline provider profile: `ado-rest` + `rocketchat-webhook` + `codex-acp`.
- Baseline deployment target: support both Docker and native, but validate Docker first because it is the fastest pilot path.
- Baseline ingress shape: prefer plugin-native webhook handling; if the installed OpenClaw hook surface is insufficient, ship a tiny bundled bridge without changing flow contracts.

## Scope

### In Scope

- `run_store` with SQLite schema, locks, dedupe, audit, and run mapping.
- `ado_client` in `ado-rest` mode for task, repo, PR, and CI operations.
- `codex_acp_runner` for task execution and resume through OpenClaw ACP.
- `rocketchat_notifier` in webhook mode.
- `openclaw-plugin` flows, hooks, skills, and runtime composition.
- `task-run`, `pr-feedback`, and `ci-recovery` flows.
- Deployment assets for Docker and native installs.
- Verification assets, runbooks, and acceptance evidence for MVP.

### Out of Scope

- `ado-mcp` as a required runtime path.
- `rocketchat-bridge` as an MVP dependency.
- Alternate ACP executors.
- PostgreSQL or multi-gateway coordination.
- Auto-merge, generalized provider marketplace, and advanced approval UI.

## Success Metrics

- One eligible Azure DevOps task creates exactly one active `TaskRun`.
- Duplicate event replay produces no duplicate run.
- Lock contention allows only one owner for a task at a time.
- One `task-run` flow can reach branch push and PR creation through Codex via ACP.
- PR comment and CI failure events resume the same session context.
- Rocket.Chat receives lifecycle notifications for started, PR opened, CI failed, blocked, and completed states.
- The same plugin bundle and config model work in Docker and native deployments.

## Workstreams

### 1. Runtime and Persistence

Objective:
Define the durable runtime backbone that survives long-running sessions and repeated events.

Deliverables:
- `run_store/schema.sql`
- lock and dedupe rules
- run and audit persistence API
- status transition rules

Dependencies:
- none

### 2. Azure DevOps Provider

Objective:
Implement the concrete provider path that all MVP flows depend on.

Deliverables:
- `ado_client` request list and request/response model
- `ado-rest` task, repo, PR, and CI operations
- event normalization contract

Dependencies:
- runtime store for run, lock, and dedupe lookup

### 3. Coding Executor

Objective:
Connect OpenClaw to Codex through ACP with a stable execution contract.

Deliverables:
- `codex_acp_runner`
- executor input/output schema
- resume and cancel support

Dependencies:
- runtime store for session and workspace mapping

### 4. OpenClaw Plugin and Flow Orchestration

Objective:
Compose the runtime, provider adapters, and executor into resumable flows.

Deliverables:
- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`
- `openclaw-plugin/skills/analyze-task`
- `openclaw-plugin/skills/implement-task`
- `openclaw-plugin/skills/fix-pr-feedback`
- `openclaw-plugin/skills/recover-ci-failure`
- ingress hooks for task, PR, and CI events

Dependencies:
- runtime store, `ado_client`, and `codex_acp_runner`

### 5. Chat Notification

Objective:
Provide low-risk human visibility without adding chat control complexity.

Deliverables:
- `rocketchat_notifier`
- notification templates for started, PR opened, CI failed, blocked, and completed

Dependencies:
- runtime store and flow status transitions

### 6. Deployment and Operations

Objective:
Package the same bundle for pilot and production-starter installation modes.

Deliverables:
- `deploy/config/openclaw.json`
- `deploy/config/providers.yaml`
- `deploy/config/harness-policy.yaml`
- `deploy/docker/compose.yml`
- `deploy/systemd/*`
- `deploy/windows/*`
- healthcheck scripts and install notes

Dependencies:
- component skeletons from the first five workstreams

## Detailed Milestones

### Milestone 0: Decision Baseline and Skeleton

Purpose:
Freeze the MVP baseline so implementation does not drift into optional paths.

Implementation:
1. Confirm `ado-rest` / `rocketchat-webhook` / `codex-acp` / SQLite as the P0 profile.
2. Create the top-level repository layout from the master plan.
3. Add config templates and placeholder flow/skill file locations.
4. Record unresolved design decisions as explicit validation tasks instead of free-form TODOs.

Exit Criteria:
- Planned directory layout exists for `run_store`, `ado_client`, `codex_acp_runner`, `rocketchat_notifier`, `openclaw-plugin`, and `deploy`.
- `providers.yaml` includes explicit mode selection and fallback fields.
- No P1 feature is needed to start the main `task-run` flow.

### Milestone 1: Runtime Core

Purpose:
Create the durable state model before any provider or flow logic is built on top.

Implementation:
1. Define the SQLite schema for `task_runs`, `task_locks`, `event_dedupe`, and `run_audit`.
2. Implement lock acquisition, lock expiry, lock release, and dedupe lookup behavior.
3. Implement status transitions for `queued -> claimed -> planning -> coding -> opening_pr -> awaiting_ci/awaiting_review` and terminal failure states.
4. Add audit helpers for fallback, retry, and human handoff events.

Exit Criteria:
- Concurrent claim attempts yield one winner and one rejected claimant.
- Replayed event fingerprints do not create a second active run.
- Run records contain enough data to resume task, PR, and CI events.

### Milestone 2: Azure DevOps Provider Baseline

Purpose:
Enable the minimum provider surface needed for task-to-PR execution.

Implementation:
1. Define the normalized event contract and request list.
2. Implement `task.get`, `task.update_status`, `task.add_comment`, `repo.prepare_workspace`, `vcs.create_branch`, `vcs.commit_and_push`, `pr.create`, `pr.get`, `pr.list_comments`, `pr.reply`, `ci.get_status`, and `ci.retry`.
3. Bind all flow-facing calls to unified capability names only.
4. Add compatibility probes that classify the environment as Azure DevOps Services or Server without changing the shared flow shape.

Exit Criteria:
- `ado-rest` supports the full MVP task, PR, and CI call set.
- No shared flow requires vendor-specific capability names.
- Environment detection results are captured as audit or startup diagnostics.

### Milestone 3: Codex ACP Executor

Purpose:
Make code generation resumable and traceable through OpenClaw ACP.

Implementation:
1. Implement executor input and output shapes from the technical design.
2. Wire session and workspace lookup through the runtime store.
3. Support new task execution, resumed execution, and controlled cancellation.
4. Return changed files, summary, check results, and follow-up items in a stable contract.

Exit Criteria:
- ACP can execute against a prepared workspace and return structured output.
- Resume uses the existing run/session mapping rather than creating a second coding context.
- Executor output is consumable by `task-run`, `pr-feedback`, and `ci-recovery`.

### Milestone 4: Main `task-run` Flow

Purpose:
Reach the first end-to-end happy path from task ingestion to PR creation.

Implementation:
1. Implement `analyze-task` and `implement-task`.
2. Build `task-run.yaml` using only unified capabilities.
3. Add ingress hook logic for task events and run claiming.
4. Gate branch push and PR creation on check results.
5. Emit task-system updates and leave notifier hook points for lifecycle chat delivery.

Exit Criteria:
- One eligible task can progress from event intake to PR creation.
- The flow records `planning`, `coding`, `opening_pr`, and `awaiting_ci` or `awaiting_review`.
- Branch push occurs only after checks run.

### Milestone 5: Resume Loops and Notifications

Purpose:
Preserve a single durable run across human review and automated failure paths, and make lifecycle visibility available to operators.

Implementation:
1. Implement `pr-feedback.yaml` and `fix-pr-feedback`.
2. Implement `ci-recovery.yaml` and `recover-ci-failure`.
3. Resolve `pr_id -> run_id` and `ci_run_id -> run_id`.
4. Add escalation behavior for unpatchable CI failures.
5. Implement `rocketchat_notifier` webhook delivery for started, PR opened, CI failed, blocked, and completed states.

Exit Criteria:
- PR comments resume the same run and publish an update.
- CI failures either patch and retry or move the run to `awaiting_human`.
- No resume path creates a second active run for the same task.
- Lifecycle notifications are emitted through the notifier without requiring threaded chat control.

### Milestone 6: Deployment and Operational Hardening

Purpose:
Package and validate the MVP in both supported install modes.

Implementation:
1. Create Docker Compose assets with mounted SQLite persistence.
2. Create native-install assets for Linux and Windows service management.
3. Add health checks, basic metrics, and environment-driven secret loading.
4. Document install, restart, rollback, and stuck-run recovery steps.

Exit Criteria:
- Docker restart preserves SQLite state and plugin artifacts.
- Native install survives reboot and starts cleanly through the selected service wrapper.
- Operators can verify system health using health endpoints or CLI checks.

## File-First Backlog

These files should be created before deeper implementation because they unblock the largest number of downstream tasks:

1. `deploy/config/providers.yaml`
2. `run_store/schema.sql`
3. `ado_client/request-list.md` or equivalent request contract artifact
4. `openclaw-plugin/flows/task-run.yaml`
5. `openclaw-plugin/skills/analyze-task`
6. `openclaw-plugin/skills/implement-task`

## Risk Register

### Risk: Azure DevOps Services vs Server compatibility differs more than expected

Mitigation:
- Implement `ado-rest` as the hard baseline.
- Add environment probes and compatibility tests before any `ado-mcp` work.

### Risk: OpenClaw webhook surface is not enough for direct event intake

Mitigation:
- Keep the ingress contract stable.
- Allow a tiny bundled bridge that only receives webhooks, writes SQLite, and wakes OpenClaw.

### Risk: Chat requirements expand into thread control too early

Mitigation:
- Lock MVP to `rocketchat-webhook`.
- Keep `chat.read_thread` and `chat.resolve_thread_target` behind a later bridge milestone.

### Risk: Flow logic drifts into vendor-specific calls

Mitigation:
- Reject `ado.*`, `rocketchat.*`, or `codex.*` names in shared flows.
- Review every flow file against the unified capability contract before closing a milestone.

### Risk: Resume logic loses context across long-running sessions

Mitigation:
- Persist task, PR, CI, workspace, and session mapping in the runtime store.
- Require resume-path tests before closing Milestone 5.

## Release Gate

MVP execution can move from planning into broad implementation only when the following are true:

- This PRD is accepted as the active work breakdown.
- `.omx/plans/test-spec-clawharness-v1-2026-04-05.md` is the active acceptance source.
- `.omx/plans/pdca-clawharness-v1-2026-04-05.md` is used as the working loop for cycle closure.
- The team agrees that all P1 items stay out of scope until Milestone 6 is stable.
