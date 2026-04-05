# ClawHarness v1 Evidence Snapshot

Date: 2026-04-05
Status: Live V1 task-to-PR + PR-feedback loop validated on Azure DevOps + OpenClaw ACP + local Rocket.Chat
Companion to:
- `.omx/plans/test-spec-clawharness-v1-2026-04-05.md`
- `.omx/plans/pdca-clawharness-v1-2026-04-05.md`

## Verification Commands

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner harness_runtime rocketchat_notifier run_store tests
python -m harness_runtime.main --task-id 29 --repo-id 06c34683-1500-42ae-a939-e68ef63ef6f6
python -m harness_runtime.main --task-id 30 --repo-id 06c34683-1500-42ae-a939-e68ef63ef6f6
```

Additional environment verification:

- `openclaw health`
- `openclaw agents list`
- `openclaw plugins list`

## Result Summary

- Local automated tests: passed, `54/54`
- Python module compile checks: passed
- OpenClaw ACP real smoke: passed
- Real Azure DevOps task `29` reached `awaiting_review` and opened PR `17`
- PDCA found one live issue in cycle 1: executor result artifact was written inside the cloned repo and got committed
- Harness was corrected so executor artifacts are written to `~/.openclaw/workspace/harness/.executor-artifacts/<run_id>/`
- Real Azure DevOps task `30` reached `awaiting_review` and opened clean PR `18`
- Real Azure DevOps task `31` reached `awaiting_review`, opened PR `19`, and later completed a live PR-feedback follow-up on the same run
- PR `18` contains only `README.md`
- PR `19` thread `79` now contains both the human review comment and the ClawHarness follow-up reply
- Superseded PR `17` was abandoned after the cycle 2 fix was validated
- Run audit evidence was persisted in `C:\Users\lus\.openclaw\harness\harness.db`

## PDCA Loop

### Cycle 0: Preflight fix

Issue:
- Azure Boards rejected `get_task` because the implementation requested `fields` and `$expand=relations` in the same call

Action:
- `harness_runtime/orchestrator.py` was corrected to request only the required fields
- regression test added in `tests/test_task_orchestrator.py`

### Cycle 1: First real end-to-end run

Work item:
- id: `29`
- html: `https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_workitems/edit/29`

Run:
- run id: `manual-ai-review-test-29`
- status: `awaiting_review`
- started: `2026-04-05T07:12:32Z`
- updated: `2026-04-05T07:14:40Z`

Repository outcome:
- branch: `refs/heads/ai/29-v1-validation-append-harness-note-to-rea`
- commit: `0c8b8a6039648620c25825e8fd3dbf8586dc3eb0`
- PR id: `17`
- PR API URL: `https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_apis/git/repositories/06c34683-1500-42ae-a939-e68ef63ef6f6/pullRequests/17`
- final PR status: `abandoned`

Observed issue:
- `git log --stat` showed both `README.md` and the repo-scoped executor result artifact in the pushed commit
- this proved the task-to-PR loop worked, but also exposed an isolation bug in harness runtime artifacts

### Cycle 2: Corrective rerun after artifact-isolation fix

Work item:
- id: `30`
- html: `https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_workitems/edit/30`

Run:
- run id: `manual-ai-review-test-30`
- status: `awaiting_review`
- started: `2026-04-05T07:17:22Z`
- updated: `2026-04-05T07:19:53Z`

Repository outcome:
- branch: `refs/heads/ai/30-v1-validation-rerun-readme-note-without-`
- commit: `8411da5ca57b1eb516590982507aea8e1f0d8c2f`
- PR id: `18`
- PR status: `active`
- PR API URL: `https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_apis/git/repositories/06c34683-1500-42ae-a939-e68ef63ef6f6/pullRequests/18`

Workspace and artifact evidence:
- workspace: `C:\Users\lus\.openclaw\workspace\harness\AI-Review-Test-manual-ai-review-test-30`
- executor result artifact: `C:\Users\lus\.openclaw\workspace\harness\.executor-artifacts\manual-ai-review-test-30\executor-result.json`
- task comment count after run: `1`

Content evidence:
- executor result summary: `Appended a V1 Harness Validation section to README.md and verified README.md is the only modified file.`
- `git log -1 --stat` for task `30` shows exactly one changed file: `README.md`
- resulting README ends with:

```md
# V1 Harness Validation
This repository was updated by the ClawHarness end-to-end validation rerun on 2026-04-05.
```

### Cycle 3: Live PR feedback resume after ACP-compatibility corrections

Work item:
- id: `31`
- html: `https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_workitems/edit/31`

Run:
- run id: `manual-ai-review-test-31`
- final status: `awaiting_review`
- session id preserved in run record: `agent:codex:acp:ebe3c03a-2979-49c4-b6a7-2b2c99f8b699`
- PR id: `19`

Live feedback evidence:
- a real review thread `79` was created on PR `19`
- the incoming comment requested one more README sentence under `Build and Test`
- ClawHarness resolved `pr_id -> run_id`, reused run `manual-ai-review-test-31`, processed the unresolved thread, and replied on the same PR thread
- run audit shows `pr_feedback_queued -> pr_feedback_loaded -> pr_feedback_executor_completed -> checks_completed -> pr_feedback_replied -> awaiting_review`

Repository evidence:
- branch: `refs/heads/ai/31-live-ac-06-validation-readme-follow-up-v`
- synced commit: `fe1d7135bbca37f88176056148411191b37e7e15`
- workspace README now contains:

```md
Recheck any README updates after review feedback to confirm the documented build and test steps still match the latest branch state.
```

Compatibility note:
- live validation exposed that completed ACP runs could not be resumed by resource id in this gateway configuration
- the harness was corrected to preserve the logical `session_id` in the run record while starting a fresh ACP execution for resume work in the same run/workspace/branch context

## Acceptance Mapping

### AC-01: Single Task Claim and Dedupe

Status:
- passed locally

Evidence:
- `tests/test_run_store.py::test_claim_run_accepts_first_request`
- `tests/test_run_store.py::test_claim_run_rejects_duplicate_event_fingerprint`
- `tests/test_run_store.py::test_claim_run_rejects_second_active_run_for_same_task`

### AC-02: Structured Planning Output

Status:
- passed locally and used in live runs

Evidence:
- `tests/test_codex_acp_runner.py::test_build_task_prompt_renders_constraints_and_artifacts`
- task prompt generation in `codex_acp_runner/runner.py`
- live tasks `29` and `30` completed through ACP with structured executor result artifacts

### AC-03: Codex ACP Coding Execution

Status:
- passed live

Evidence:
- `tests/test_codex_acp_runner.py::test_build_spawn_payload_uses_acp_runtime`
- `tests/test_codex_acp_runner.py::test_resume_includes_resume_session_id`
- `tests/test_openclaw_client.py::test_invoke_tool_posts_to_tools_invoke_endpoint`
- live run `manual-ai-review-test-30` completed with executor result artifact at `C:\Users\lus\.openclaw\workspace\harness\.executor-artifacts\manual-ai-review-test-30\executor-result.json`

### AC-04: Check Gate Before PR

Status:
- passed live for the minimal repo profile used in V1 validation

Evidence:
- live run `manual-ai-review-test-30` recorded `checks_completed` before branch push and PR creation
- local gate implementation in `harness_runtime/orchestrator.py`
- run-store audit shows `git diff --check` passed before transition to `opening_pr`

Remaining gap:
- broader language/tooling matrices beyond the minimal repo profile still need live validation

### AC-05: Branch Push and PR Creation

Status:
- passed live

Evidence:
- live task `30` pushed branch `refs/heads/ai/30-v1-validation-rerun-readme-note-without-`
- live task `30` opened PR `18`
- `tests/test_ado_client.py::test_create_pull_request_builds_expected_payload`

### AC-06: PR Feedback Resume

Status:
- passed live

Evidence:
- `tests/test_harness_runtime.py::test_pr_event_queues_existing_run_into_runtime_orchestrator`
- `tests/test_task_orchestrator.py::test_resume_from_pr_feedback_reuses_session_and_replies_without_new_run`
- `tests/test_run_store.py::test_update_run_fields_and_lookup_by_pr_and_ci`
- live run `manual-ai-review-test-31` resumed from PR `19`
- PR thread `79` contains the human review comment and the ClawHarness reply comment `2`
- live run audit for `manual-ai-review-test-31` preserved the same `run_id` and `session_id` while returning the run to `awaiting_review`

### AC-07: CI Failure Recovery

Status:
- passed locally, live validation blocked by missing CI builds in the target Azure DevOps project

Evidence:
- `tests/test_harness_runtime.py::test_ci_event_queues_existing_run_into_runtime_orchestrator_and_notifies`
- `tests/test_task_orchestrator.py::test_resume_from_ci_failure_retries_build_and_updates_run`
- `tests/test_task_orchestrator.py::test_resume_from_ci_failure_escalates_when_executor_requires_human`
- `tests/test_ado_client.py::test_retry_build_queues_new_build_from_existing_metadata`

Blocking fact:
- on 2026-04-05, `AzureDevOpsRestClient.list_builds(top=10)` returned `[]` for `AI-Review-Test`, so there was no live build definition/run available to trigger a real `ci.run.failed` recovery cycle

### AC-08: Rocket.Chat Lifecycle Notifications

Status:
- passed locally and live on Windows

Evidence:
- `tests/test_rocketchat_notifier.py`
- lifecycle payload builder in `rocketchat_notifier/notifier.py`
- local Rocket.Chat workspace started on `http://127.0.0.1:3000`
- local incoming webhook created at `RC_WEBHOOK_URL` and smoke-tested successfully
- end-to-end bridge event with synthetic task `AI-Review-Test#991369552` produced message `Task AI-Review-Test#991369552 claimed and dispatched to OpenClaw` in channel `#ai-dev`
- capability verification script confirmed:
  - group chat delivery: passed
  - direct message delivery to `@botpeer`: passed
  - image attachment delivery to `#ai-dev`: passed
  - OpenClaw-specific slash command presence: not implemented in current workspace

Implementation note:
- bridge notification failures append `notification_failed` audit records instead of breaking the incoming webhook request path

### AC-09: Docker Deployment Support

Status:
- implementation assets complete, live validation pending

Evidence:
- `deploy/docker/compose.yml`
- `deploy/docker/harness-bridge.Dockerfile`
- `deploy/docker/.env.example`

Remaining gap:
- Docker runtime was not available in this session for a live compose startup test

### AC-10: Native Deployment Support

Status:
- Windows native deployment validated live; Linux service-manager validation pending

Evidence:
- `deploy/systemd/openclaw.service`
- `deploy/systemd/harness-bridge.service`
- `deploy/windows/install-openclaw.ps1`
- `deploy/windows/install-rocketchat-local.ps1`
- `deploy/windows/run-harness.ps1`
- local OpenClaw plugin load fixed with linked install + plugin-local runtime deps
- local hooks ingress validated with a live `task.created` webhook returning `202 task_dispatched`
- Azure DevOps PAT validated against `https://dev.azure.com/lusipad`
- live Azure DevOps task `30` completed through `python -m harness_runtime.main`
- local Rocket.Chat workspace, channel, webhook integration, and bridge notifications validated on Windows loopback

Remaining gap:
- antivirus heuristics on this Windows host treated Startup-folder persistence and hidden background launchers as suspicious, so Windows delivery was kept as explicit foreground startup
- no live Linux service-manager run was executed in this session

### AC-11: Workflow-Stability Rule

Status:
- passed locally

Evidence:
- shared flow drafts use unified capability names only
- prior static search found no `ado.*`, `rocketchat.*`, or `codex.*` calls in `openclaw-plugin/flows`

### AC-12: Security and Policy Guardrails

Status:
- partially implemented

Evidence:
- `deploy/config/harness-policy.yaml`
- protected-branch and no-merge policy captured in config and skill contracts
- live secret wiring through user environment variables validated on Windows

Remaining gap:
- protected-branch enforcement, required reviewers, and branch-policy interactions still need live validation

### AC-13: Observability and Audit

Status:
- passed live for runtime audit, partially implemented for operational telemetry

Evidence:
- run audit persisted in `C:\Users\lus\.openclaw\harness\harness.db`
- live audit chain recorded for runs `manual-ai-review-test-29` and `manual-ai-review-test-30`
- audit assertions in run-store and bridge tests
- deployment healthcheck scripts in `deploy/scripts/`

Remaining gap:
- metrics export and live service telemetry still need environment validation

## Residual Risks

- Live CI failure recovery is still blocked by the absence of CI builds/definitions in the current Azure DevOps validation project.
- Docker and Linux native service assets are present, but startup validation still requires the target runtime.
- Protected-branch, reviewer, and CI-policy interactions may still require small adapter changes in the first fully governed repository.
- ClawHarness V1 closure is now proven for the task -> ACP -> checks -> branch -> PR -> feedback -> fix path, but not yet for the CI-failure -> patch/retry continuation path.
