# ClawHarness

English | [简体中文](README.zh-CN.md)

ClawHarness is an autonomous task-to-PR execution harness for Azure DevOps and GitHub repositories. It connects provider task sources, OpenClaw execution, local repository verification, branch and PR automation, and optional Rocket.Chat lifecycle notifications into one repeatable delivery loop.

## What It Does

- Uses a SQLite-backed runtime store for task claiming, deduplication, locking, and audit records
- Prepares an isolated workspace for each task run and creates a task branch
- Calls Codex through OpenClaw or the local Codex CLI backend to implement changes
- Runs local checks before commit and push
- Opens PRs automatically and keeps an audit trail for every run
- Supports webhook-driven continuation for PR feedback and CI failure recovery
- Supports provider-neutral routing across Azure DevOps and GitHub
- Ships deployment assets for Windows, Linux systemd, and Docker

## Repository Layout

- `ado_client/`: Azure DevOps REST client for work items, repositories, PRs, and builds
- `codex_acp_runner/`: ACP executor wrapper and structured result handling
- `github_client/`: GitHub REST client for issues, PR comments, and checks
- `harness_runtime/`: bridge service, orchestration logic, and runtime config loading
- `rocketchat_notifier/`: Rocket.Chat webhook notifier
- `run_store/`: SQLite schema and runtime persistence primitives
- `workflow_provider/`: shared provider-neutral event and client contracts
- `openclaw-plugin/`: OpenClaw plugin entry, hooks, flows, and skills
- `deploy/`: Docker, systemd, Windows, and config assets
- `.omx/plans/`: PRD, test spec, PDCA records, and validation evidence

## Documentation Map

- `deploy/README.md`: deployment options, configuration, and operations notes
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`: V2 product definition and scope
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`: V2 acceptance criteria and validation gates
- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`: latest live-validation evidence snapshot
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`: V1 live-validation history and PDCA evidence

## Current Status

- Azure DevOps task-to-branch-to-PR is live-validated
- Same-parent PR feedback recovery is live-validated
- Same-parent CI recovery is live-validated end to end:
  work item `45` -> run `manual-ai-review-test-45` -> PR `27` -> failed build `42` -> child run `manual-ai-review-test-45--ci-recovery--f7ccbe33` -> successful retry build `43`
- The local Docker stack is live-validated with:
  `openclaw-gateway`, `clawharness-bridge`, and `openclaw-bot-view`
- The Windows self-hosted Azure agent issue has been live-debugged and fixed; the documented recovery path is now part of `deploy/README.md`
- GitHub provider support is implemented and covered by local tests, but live GitHub webhook validation is still blocked because `GITHUB_TOKEN` is not configured

## Current V2 Delivery

- The bridge now exposes read-only runtime APIs for run summaries, run lists, run details, audit timelines, and run graphs
- PR feedback and CI recovery now create follow-up child runs under the same parent run, with checkpoints and artifact records
- PR feedback and CI recovery now run in single-flight mode per parent run and relation type, using a follow-up lock budget that covers executor timeout with an extra 300-second buffer so one recovery lane cannot race another on the same branch/workspace/session
- Rocket.Chat command ingress now supports `status`, `detail`, `pause`, `resume`, `add-context`, and `escalate`, with conversation-to-run binding and audited command application
- Image attachments added through chat context can now be analyzed through the OpenAI-compatible `responses` API and recorded back into the run evidence chain as `image-analysis`
- The runtime core now routes task, PR feedback, and CI recovery through provider adapters instead of Azure-only action names
- GitHub issue, PR comment, and checks failure webhooks now map into the same run graph and status model as Azure DevOps
- The runtime now auto-selects versioned ClawHarness skill packs per run kind and agent role, and records the selection into run evidence for audit
- The runtime now ships a maintenance entry point for retention-based workspace cleanup without touching active run recovery state
- Docker now includes an optional `bot-view` profile for an OpenClaw dashboard sidecar
- The sidecar also exposes a `/clawharness` page that proxies ClawHarness run and audit data into the dashboard surface

## Quick Start

1. Configure the required environment variables for your task provider.
   For Azure DevOps, set `ADO_BASE_URL`, `ADO_PROJECT`, and `ADO_PAT`.
   For GitHub, switch `deploy/config/providers.yaml` to the GitHub profile and set `GITHUB_TOKEN`.
   In both cases, set `OPENCLAW_HOOKS_TOKEN` and `OPENCLAW_GATEWAY_TOKEN`.
2. Review deployment options in `deploy/README.md`.
3. Run the Windows installer scripts or use the Docker/systemd assets for your target environment.
4. Run the automated checks:

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner github_client harness_runtime rocketchat_notifier run_store workflow_provider tests
```

5. Trigger a manual task run:

```sh
python -m harness_runtime.main --task-id <task-id> --repo-id <repo-id> [--provider-type github]
```

## Validation Scope

The current implementation is already live-validated on the Azure-based core loop:

- task claim and dedupe
- execution
- local check gate
- branch push
- PR creation
- same-parent continuation after PR feedback and CI recovery, including child-run evidence

The main remaining gaps that still need broader live validation are:

- GitHub issue-to-PR and checks recovery in a real repository with live webhook delivery
- policy interaction in repositories with stricter protected-branch and review rules
- broader Linux native and non-local deployment validation
