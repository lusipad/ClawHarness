# ClawHarness v1 Acceptance Test Specification

Date: 2026-04-05
Status: Acceptance baseline
Companion to:
- `.omx/plans/prd-clawharness-v1-2026-04-05.md`
- `.omx/plans/clawharness-master-plan-2026-04-05.md`

## Baseline Sources

- Core MVP acceptance and build order come from `.omx/plans/clawharness-master-plan-2026-04-05.md:379-426`.
- Provider compatibility, workflow-stability rules, and deployment validation come from `.omx/plans/clawharness-support-matrix-2026-04-05.md:209-497`.
- TaskFlow, skill, executor, deployment, security, and monitoring requirements come from `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md:445-784`.

## Acceptance Philosophy

- Every acceptance criterion must be testable through observable evidence.
- Shared flows are accepted only if they remain vendor-neutral and rely on unified capabilities.
- Resume behavior is accepted only if the same run/session context is reused.
- Docker and native support are both P0; neither can be deferred out of MVP closure.
- P1 features such as `ado-mcp` or `rocketchat-bridge` must not be prerequisites for passing MVP acceptance.

## Test Levels

### Level 1: Static and Artifact Validation

Purpose:
Verify that required files, schemas, config templates, and flow references exist and are internally consistent.

Required evidence:
- schema files
- provider and policy config templates
- flow and skill definitions
- deployment assets

### Level 2: Component Validation

Purpose:
Verify each module in isolation before attempting end-to-end flows.

Required evidence:
- run-store tests for dedupe, locking, and status transitions
- Azure DevOps adapter tests for task, PR, and CI operations
- ACP executor tests for run, resume, and cancel behavior
- Rocket.Chat notifier tests for webhook payload generation

### Level 3: Flow Integration Validation

Purpose:
Verify the main runtime loops.

Required evidence:
- `task-run` happy path
- `pr-feedback` resume path
- `ci-recovery` patch or escalate path

### Level 4: Operational Validation

Purpose:
Verify the deployment, policy, and operability envelope.

Required evidence:
- Docker restart persistence
- native service restart behavior
- health checks
- audit events
- secret handling

## Acceptance Criteria

### AC-01: Single Task Claim and Dedupe

Requirement:
One eligible Azure DevOps task creates exactly one active run.

Given:
- one eligible task event
- one or more duplicate deliveries of the same event

When:
- the event intake path normalizes and processes the event

Then:
- exactly one `TaskRun` is created
- a lock is held by one owner only
- duplicate deliveries are recorded as deduped events, not new runs

Evidence:
- runtime store record for the created run
- dedupe record for replayed events
- audit or logs showing one accepted claim and rejected duplicates

### AC-02: Structured Planning Output

Requirement:
OpenClaw produces a structured plan for the task before coding.

Given:
- a normalized task payload
- repository context

When:
- `analyze-task` executes

Then:
- the output contains a plan summary
- impacted files or modules are listed
- missing information and risk level are explicit

Evidence:
- saved `analyze-task` output artifact
- flow state showing transition into `planning`

### AC-03: Codex ACP Coding Execution

Requirement:
OpenClaw invokes Codex through ACP and receives structured execution output.

Given:
- a prepared workspace
- executor input matching the documented contract

When:
- `executor.run_coding_task` or resume is called

Then:
- execution returns `status`, `summary`, `changed_files`, `checks`, and `follow_up`
- the run remains tied to the same session and workspace

Evidence:
- executor result artifact
- runtime mapping of `run_id`, `session_id`, and `workspace_path`

### AC-04: Check Gate Before PR

Requirement:
The main flow runs checks before branch push and PR creation.

Given:
- a coding result with candidate file changes

When:
- `task-run` reaches its verification stage

Then:
- checks run before `vcs.commit_and_push`
- failed checks block PR creation or force explicit escalation

Evidence:
- ordered flow log or audit entries
- check result artifact
- absence of PR creation on failing checks

### AC-05: Branch Push and PR Creation

Requirement:
The system can create a branch and PR in the configured repository.

Given:
- a successful coding and checks stage

When:
- `task-run` reaches release actions

Then:
- a task-scoped branch is created
- code is pushed
- a PR is opened
- the run status becomes `awaiting_ci` or `awaiting_review`

Evidence:
- branch name in run record
- PR identifier in run record
- provider adapter output for push and PR creation

### AC-06: PR Feedback Resume

Requirement:
A PR comment resumes the same run and session.

Given:
- an existing run with `pr_id`
- a new PR comment event

When:
- `pr-feedback` processes the event

Then:
- the system resolves `pr_id -> run_id`
- the same session is resumed
- unresolved review comments are processed
- changes are pushed without creating a second run

Evidence:
- mapping lookup artifact
- flow log for `pr-feedback`
- unchanged `run_id` and `session_id`

### AC-07: CI Failure Recovery

Requirement:
A CI failure resumes the same run and either patches or escalates.

Given:
- an existing run with `ci_run_id`
- a failed CI event

When:
- `ci-recovery` processes the event

Then:
- the system resolves `ci_run_id -> run_id`
- the same run is resumed
- the result is either a patch-and-retry path or an `awaiting_human` escalation

Evidence:
- CI lookup artifact
- recovery decision record
- retry output or escalation audit entry

### AC-08: Rocket.Chat Lifecycle Notifications

Requirement:
Rocket.Chat receives MVP lifecycle notifications.

Given:
- status transitions for started, PR opened, CI failed, blocked, and completed

When:
- flows emit chat updates

Then:
- webhook payloads are generated for each required event
- delivery success or failure is recorded

Evidence:
- notifier payload fixtures or integration logs
- audit entries for sent notifications

### AC-09: Docker Deployment Support

Requirement:
The MVP bundle runs in Docker with persistent runtime state.

Given:
- the Docker deployment profile

When:
- services are started, stopped, and restarted

Then:
- SQLite state survives restart
- plugin artifacts remain available
- the ACP executor can reach the workspace
- chat notifications can still be delivered

Evidence:
- Docker smoke test results
- persisted runtime records after restart
- health check results

### AC-10: Native Deployment Support

Requirement:
The same bundle runs through native service installation.

Given:
- the native deployment profile

When:
- services are installed and restarted

Then:
- OpenClaw starts cleanly
- runtime store permissions are correct
- the service wrapper survives reboot or simulated restart
- the webhook listener is reachable if a bridge is required

Evidence:
- native install script results
- service status output
- health check or listener reachability proof

### AC-11: Workflow-Stability Rule

Requirement:
Shared flows remain provider-neutral.

Given:
- all flow definitions

When:
- the flows are reviewed before release

Then:
- flows reference only unified capability names
- vendor-specific call names do not appear in shared flow logic

Evidence:
- flow review checklist
- static search results proving absence of forbidden names

### AC-12: Security and Policy Guardrails

Requirement:
The MVP respects the stated v1 policy boundaries.

Given:
- configured repositories and deployment environment

When:
- the system performs coding and PR operations

Then:
- no direct push to protected branches occurs
- merge automation is absent
- provider secrets come from environment or secret files
- service identities are separated by function

Evidence:
- branch policy config
- deployment config review
- secret-loading documentation and smoke checks

### AC-13: Observability and Audit

Requirement:
Operators can understand run health and investigate failures.

Given:
- normal and failure scenarios

When:
- runs progress across the main flows

Then:
- run lifecycle, duplicate suppression, lock contention, and executor failures are visible
- audit records exist for claims, fallbacks, retries, and human handoffs

Evidence:
- metrics output or logs
- audit records for sample runs

## Verification Sequence

1. Run Level 1 static validation before any integration testing.
2. Run Level 2 component validation for `run_store`, `ado_client`, `codex_acp_runner`, and `rocketchat_notifier`.
3. Run Level 3 flow tests in this order: `task-run`, `pr-feedback`, `ci-recovery`.
4. Run Level 4 operational checks for Docker and native profiles.
5. Re-run the affected acceptance criteria after every failed check and fix.

## Exit Criteria

The MVP is accepted only when all of the following are true:

- AC-01 through AC-13 pass.
- No P0 or P1 defect remains open against the accepted scope.
- Both Docker and native profiles have evidence bundles.
- Shared flows satisfy the workflow-stability rule.
- Resume paths prove stable `run_id` reuse.
- Security and policy constraints are verified, not assumed.

## Failure Handling Rules

- A failed Level 1 or Level 2 check blocks downstream flow validation.
- A failed `task-run` check blocks PR feedback and CI recovery sign-off.
- A failed Docker or native operational check blocks MVP closure.
- A resume-path bug is treated as release-blocking because it breaks the core OpenClaw continuation model.

## Evidence Package Template

Each completed cycle should deposit or reference:

- changed files
- executed verification steps
- pass/fail result per acceptance criterion
- raw evidence locations
- residual risks
- follow-up backlog items
