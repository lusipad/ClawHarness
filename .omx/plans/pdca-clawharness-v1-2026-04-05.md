# ClawHarness v1 PDCA Execution Loop

Date: 2026-04-05
Status: Core V1 closure validated through live PR feedback; CI and deployment follow-up cycles still open
Companion to:
- `.omx/plans/prd-clawharness-v1-2026-04-05.md`
- `.omx/plans/test-spec-clawharness-v1-2026-04-05.md`

## Objective

Run the ClawHarness MVP through short PDCA cycles so that every implementation increment is scoped, verified, and either stabilized or corrected before the next slice begins.

## Operating Rules

- Each cycle owns one bounded milestone or one high-risk cross-cutting issue.
- No cycle starts without explicit acceptance targets mapped to the test spec.
- No cycle closes without evidence for completed work and a decision on remaining risks.
- Optional P1 items stay out of cycle scope unless a later ADR changes the cut line.
- If a check fails, the cycle stays open and loops through corrective action instead of reporting partial completion.

## Standard PDCA Template

### Plan

Required outputs:
- cycle objective
- exact in-scope files or modules
- acceptance criteria IDs from the test spec
- risks, assumptions, and entry conditions
- expected proof artifacts

### Do

Required actions:
- implement only the planned scope
- capture changed files and notable design decisions
- record verification commands or procedures as they are executed

### Check

Required outputs:
- pass/fail result for each targeted acceptance criterion
- evidence links or artifact paths
- defect list with severity
- gap analysis between expected and actual behavior

### Act

Required outputs:
- decision to keep, fix, narrow, or expand scope
- backlog updates
- plan adjustments for the next cycle
- ADR or policy update if a fixed decision changes

## Cycle Closure Checklist

- planned files were changed or explicitly deferred
- planned acceptance criteria were executed
- failures were either fixed or carried as explicit blockers
- residual risks were recorded
- the next cycle has a clean entry condition

## Initial Cycle Map

### Cycle 0: Baseline and Skeleton

Plan:
- establish the repository skeleton
- create `providers.yaml`, `schema.sql`, and flow/skill placeholders
- confirm P0 profile assumptions

Do:
- create skeleton files and baseline config contracts
- document unresolved questions as validation tasks

Check:
- validate file presence and config completeness
- confirm no P1 dependency is required for the happy path

Act:
- freeze the baseline profile
- move unresolved environment questions into the validation backlog

Target acceptance:
- AC-11
- partial AC-12

### Cycle 1: Runtime Core

Plan:
- implement `run_store`
- define status transitions, locks, dedupe, and audit

Do:
- build schema and persistence APIs
- implement concurrency-safe claim logic

Check:
- run lock, dedupe, and status-transition verification
- inspect audit records for fallback and retry support

Act:
- adjust schema or locking rules based on failed concurrency cases

Target acceptance:
- AC-01
- partial AC-13

### Cycle 2: Azure DevOps Provider Baseline

Plan:
- implement `ado-rest` task, repo, PR, and CI operations
- add event normalization

Do:
- build the concrete adapter and request contract
- wire unified capability names

Check:
- validate all MVP provider calls
- verify shared flows do not depend on vendor-specific names

Act:
- keep `ado-mcp` out of scope unless `ado-rest` is stable

Target acceptance:
- partial AC-05
- AC-11

### Cycle 3: Codex ACP Executor and Main Flow

Plan:
- implement the ACP executor path
- implement `analyze-task`, `implement-task`, and `task-run`

Do:
- wire workspace preparation, coding execution, checks, push, and PR creation

Check:
- verify structured planning output
- verify executor output contract
- verify check gate before PR
- verify task-to-PR happy path

Act:
- refine executor contract or flow sequencing if the happy path fails

Target acceptance:
- AC-02
- AC-03
- AC-04
- AC-05

### Cycle 4: Resume Loops

Plan:
- implement `pr-feedback` and `ci-recovery`
- add run/session lookup for PR and CI events

Do:
- build resume-path flows and escalation behavior

Check:
- verify stable `run_id` reuse
- verify patch-or-escalate CI behavior

Act:
- tighten mapping or escalation rules if any resume path forks incorrectly

Target acceptance:
- AC-06
- AC-07

### Cycle 5: Notifications and Deployment

Plan:
- implement Rocket.Chat notifications
- package Docker and native deployment assets

Do:
- wire lifecycle notifications
- create Docker Compose and native-service install assets
- add health checks

Check:
- verify Docker persistence and native service behavior
- verify notifier payloads and delivery records

Act:
- fix operational gaps before broadening provider modes

Target acceptance:
- AC-08
- AC-09
- AC-10
- partial AC-12
- partial AC-13

### Cycle 6: Hardening and Release Gate

Plan:
- close observability, policy, and residual defects
- assemble the evidence package

Do:
- rerun the full acceptance suite
- close release-blocking gaps
- finalize runbooks

Check:
- confirm AC-01 through AC-13 all pass
- confirm both deployment profiles are proven

Act:
- declare MVP ready or open another corrective cycle with a narrowed scope

Target acceptance:
- AC-01 through AC-13

## Daily Working Rhythm

For each active cycle:

1. Refresh the cycle plan with scope, changed files, and target criteria.
2. Execute implementation only for the planned slice.
3. Run the targeted checks before claiming cycle progress.
4. Record evidence and residual risks.
5. Either close the cycle or open a corrective sub-cycle.

## Escalation Rules

- A release-blocking failure in locking, dedupe, resume mapping, or deployment persistence triggers an immediate corrective cycle.
- A question that changes fixed v1 scope requires an ADR update before more implementation continues.
- A provider-specific shortcut that breaks the unified-capability rule must be removed before the cycle can close.

## Metrics Tracked Per Cycle

- target acceptance criteria count
- passed criteria count
- failed criteria count
- defects opened and closed
- time from cycle start to verified closure
- unresolved risks carried forward

## Cycle Status Template

Use this structure at the end of each cycle:

```md
## Cycle <n> Status

Objective:
- ...

Planned scope:
- ...

Changed files:
- ...

Acceptance results:
- AC-xx: passed | failed | blocked

Evidence:
- ...

Residual risks:
- ...

Act decision:
- continue | corrective cycle | re-scope
```

## Current Starting Point

The repository-scoped implementation work is complete for the current session:

- Cycle 0:
  - planning artifacts, skeleton directories, flow drafts, and baseline config files exist
- Cycle 1:
  - `run_store` has an executable Python SQLite implementation for claim, lock, dedupe, status transition, lookup, and audit behavior
- Cycle 2:
  - `ado_client` has an executable Python `ado-rest` baseline for task, PR, CI, and event-normalization operations
- Cycle 3:
  - `codex_acp_runner` has an executable ACP payload builder, task prompt formatter, and resume-session contract
- Cycle 4:
  - PR feedback and CI recovery orchestration are implemented in `harness_runtime/bridge.py` and `harness_runtime/orchestrator.py`
- Cycle 5:
  - `rocketchat_notifier` exists
  - Docker, systemd, Windows service, and healthcheck assets exist
  - OpenClaw native plugin metadata and skill bundles exist
- Cycle 6:
  - local evidence bundle exists in `.omx/plans/evidence-clawharness-v1-2026-04-05.md`

Verification evidence currently includes:

- Python compile checks for all implemented modules
- `python -m unittest discover -s tests -v` passing with 54 tests
- JSON syntax validation for `deploy/config/openclaw.json`, `openclaw-plugin/package.json`, and `openclaw-plugin/openclaw.plugin.json`
- `python -m harness_runtime.main --help` CLI smoke check
- live OpenClaw ACP smoke execution with structured executor result output
- live Azure DevOps work item `29` reaching branch + PR creation, which exposed the result-artifact isolation bug
- corrective fix for task context loading and executor artifact isolation
- live Azure DevOps work item `30` reaching branch + clean PR creation with only `README.md` changed
- live Azure DevOps work item `31` reaching PR `19` and then completing a real PR-feedback follow-up on the same `run_id`
- run-store audit persisted in `C:\Users\lus\.openclaw\harness\harness.db`

Remaining work is environment-bound rather than repository-bound:

- real CI failure recovery verification
- live Docker and Linux native service startup verification
- protected-branch / reviewer / CI policy verification

## Cycle 3 Corrective Status

Objective:
- prove the V1 core task -> ACP -> checks -> branch -> PR loop against the real Azure DevOps project

Planned scope:
- `ado_client`
- `codex_acp_runner`
- `harness_runtime`
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`

Changed files:
- `ado_client/client.py`
- `codex_acp_runner/runner.py`
- `harness_runtime/orchestrator.py`
- `harness_runtime/openclaw_client.py`
- `harness_runtime/bridge.py`
- `harness_runtime/main.py`
- `harness_runtime/config.py`
- `tests/test_ado_client.py`
- `tests/test_codex_acp_runner.py`
- `tests/test_openclaw_client.py`
- `tests/test_harness_runtime.py`
- `tests/test_task_orchestrator.py`
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`

Acceptance results:
- AC-02: passed
- AC-03: passed live
- AC-04: passed live for the minimal repo profile
- AC-05: passed live

Evidence:
- cycle 1 live run: work item `29`, PR `17`, issue discovered and captured
- cycle 2 live run: work item `30`, active PR `18`, clean single-file diff
- full automated test suite: `54/54` passing

Residual risks:
- AC-06 and AC-07 were still only locally validated at the end of cycle 3
- Docker and Linux deployment profiles still need live verification

Act decision:
- close the V1 core happy-path loop
- keep later corrective cycles focused on resume paths, governed repos, and deployment validation

## Cycle 4 Corrective Status

Objective:
- close the live PR feedback loop and harden ACP resume compatibility against the installed gateway behavior

Planned scope:
- `harness_runtime/orchestrator.py`
- `harness_runtime/bridge.py`
- `run_store/store.py`
- `tests/test_harness_runtime.py`
- `tests/test_task_orchestrator.py`
- `tests/test_run_store.py`
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`
- `.omx/plans/pdca-clawharness-v1-2026-04-05.md`

Changed files:
- `harness_runtime/orchestrator.py`
- `harness_runtime/bridge.py`
- `run_store/store.py`
- `tests/test_harness_runtime.py`
- `tests/test_task_orchestrator.py`
- `tests/test_run_store.py`
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`
- `.omx/plans/pdca-clawharness-v1-2026-04-05.md`

Acceptance results:
- AC-06: passed live
- AC-07: passed locally, live blocked by missing CI builds in the validation project

Evidence:
- live task `31` opened PR `19` with run `manual-ai-review-test-31`
- PR thread `79` was created with a real review comment and later received a ClawHarness reply on the same thread
- live run audit returned `manual-ai-review-test-31` to `awaiting_review` after `pr_feedback_replied`
- full automated test suite: `54/54` passing
- `python -m compileall ado_client codex_acp_runner harness_runtime rocketchat_notifier run_store tests`: passed

Residual risks:
- the current Azure DevOps validation project had no build definitions or build runs on 2026-04-05, so AC-07 could not be exercised live
- Docker and Linux deployment profiles still need live verification
- protected-branch / reviewer / CI-policy interactions still need a governed target repository

Act decision:
- treat the V1 collaboration loop as closed through PR feedback
- keep the next corrective cycle focused on CI recovery in the first project that has a real build definition
