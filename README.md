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
- Supports an offline `local-task` mode for local repositories, local task files, and local review artifacts
- Ships exportable deployment bundles with `load-images` and `up-offline` scripts for air-gapped environments
- Ships deployment assets for Windows, Linux systemd, and Docker

## Repository Layout

- `ado_client/`: Azure DevOps REST client for work items, repositories, PRs, and builds
- `codex_acp_runner/`: ACP executor wrapper and structured result handling
- `github_client/`: GitHub REST client for issues, PR comments, and checks
- `harness_runtime/`: bridge service, orchestration logic, and runtime config loading
- `local_client/`: local offline task provider for repository, task file, and review artifact workflows
- `rocketchat_notifier/`: Rocket.Chat webhook notifier
- `run_store/`: SQLite schema and runtime persistence primitives
- `skills/`: canonical ClawHarness skill source and registry
- `workflow_provider/`: shared provider-neutral event and client contracts
- `openclaw-plugin/`: OpenClaw plugin entry, hooks, flows, and generated skill mirror for OpenClaw consumption
- `deploy/`: Docker, systemd, Windows, and config assets
- `.omx/plans/`: PRD, test spec, PDCA records, and validation evidence

## Documentation Map

- `deploy/README.md`: deployment options, configuration, and operations notes
- `skills/README.md`: canonical skill ownership and projection notes
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`: V2 product definition and scope
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`: V2 acceptance criteria and validation gates
- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`: latest live-validation evidence snapshot
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`: V1 live-validation history and PDCA evidence

## Current Status

- Latest local verification:
  `python -m unittest discover -s tests -v` -> `160/160` passed
- Azure DevOps task-to-branch-to-PR is live-validated
- Same-parent PR feedback recovery is live-validated
- Same-parent CI recovery is live-validated end to end:
  work item `45` -> run `manual-ai-review-test-45` -> PR `27` -> failed build `42` -> child run `manual-ai-review-test-45--ci-recovery--f7ccbe33` -> successful retry build `43`
- PR merge closure is now live-validated on the main loop:
  merged PR events are normalized to `pr.merged`, the root run is marked `completed`, and the provider-side task is synced automatically when supported
- The Azure hello-world closure path is now verified end to end:
  work item `46` -> run `manual-ai-review-test-46` -> PR `28` -> build `44` -> PR merged -> run completed -> Azure work item completed
- The local Docker stack is live-validated with:
  `openclaw-gateway`, `clawharness-bridge`, and `openclaw-bot-view`
- The offline Docker `local-task` path is now live-validated end to end:
  task file `task-002` -> run `manual-local-repo-task-002` -> branch `refs/heads/ai/task-002-add-offline-validation-note` -> local commit `4cca6c1` -> local review artifact `local-0eedc568`
- The default offline safety behavior is also live-validated:
  with `LOCAL_PUSH_ENABLED=0`, the source repository stays unchanged while the isolated workspace receives the branch and commit
- The `bot-view` control plane is now live-validated on the Docker stack:
  `/clawharness` read APIs, `Pause`, `Resume`, `Add Context`, and the audit-chain updates all work against a real run
- The Windows self-hosted Azure agent issue has been live-debugged and fixed; the documented recovery path is now part of `deploy/README.md`
- GitHub provider support now has live webhook ingress validated through `smee.io` into a dedicated local bridge, with real GitHub issue events creating GitHub-backed runs and preparing Windows workspaces
- GitHub issue-to-PR on Windows is now live-validated for the harness stdin rerun path:
  issue `#7` -> run `34a87604-6c44-4177-86b1-7676cb77f6cf` -> PR `8`
- GitHub PR feedback and checks recovery remain implemented, but still need broader live webhook validation in a real repository

## Recommended Today

- Use Docker as the default deployment path
- Use Azure DevOps if you want the fully live-validated provider path today
- Turn on the optional `bot-view` profile if you want a browser dashboard for OpenClaw and ClawHarness runtime status
- If you enable interactive `bot-view` controls, set `HARNESS_CONTROL_TOKEN`; set `HARNESS_API_TOKEN` or `HARNESS_READONLY_TOKEN` only if you want a stricter read/write split
- Treat the Windows GitHub issue-to-PR stdin rerun path as live-validated, but keep GitHub PR feedback and checks recovery scoped as pending broader webhook validation

## Current V2 Delivery

- The bridge now exposes read-only runtime APIs for run summaries, run lists, run details, audit timelines, and run graphs
- The bridge now also exposes a controlled `POST /api/runs/<run_id>/command` surface for audited `pause`, `resume`, `add-context`, and `escalate` actions
- PR merge events now close the root run automatically through a provider-neutral `pr.merged` event
- After a merged PR closes the run, the bridge now attempts provider-side task completion automatically for Azure DevOps and GitHub
- If provider task completion fails, the run remains `completed` and the failure is recorded as `task_completion_sync_failed` audit evidence instead of rolling the loop back
- PR feedback and CI recovery now create follow-up child runs under the same parent run, with checkpoints and artifact records
- PR feedback and CI recovery now run in single-flight mode per parent run and relation type, using a follow-up lock budget that covers executor timeout with an extra 300-second buffer so one recovery lane cannot race another on the same branch/workspace/session
- Rocket.Chat command ingress now supports `status`, `detail`, `pause`, `resume`, `add-context`, and `escalate`, with conversation-to-run binding and audited command application
- A Weixin-compatible command webhook is now available at `POST /webhooks/chat/weixin`, reusing the same command semantics as Rocket.Chat
- Image attachments added through chat context can now be analyzed through the OpenAI-compatible `responses` API and recorded back into the run evidence chain as `image-analysis`
- The runtime core now routes task, PR feedback, and CI recovery through provider adapters instead of Azure-only action names
- GitHub issue, PR comment, and checks failure webhooks now map into the same run graph and status model as Azure DevOps
- The runtime now auto-selects versioned ClawHarness skill packs per run kind and agent role, and records the selection into run evidence for audit
- The runtime now ships a maintenance entry point for retention-based workspace cleanup without touching active run recovery state
- Docker now includes an optional `bot-view` profile for an OpenClaw dashboard sidecar
- The sidecar also exposes a `/clawharness` page that proxies ClawHarness run and audit data into the dashboard surface, adds completion and intervention summaries, and provides a controlled operator panel for `Pause`, `Resume`, `Escalate`, and `Add Context`
- The runtime now includes a `local-task` provider for offline or lab environments:
  local task file -> local workspace clone -> local branch -> local commit -> local review artifact
- The deployment bundle exporter now emits `load-images` and `up-offline` scripts so Docker stacks can be copied into offline environments without rebuilding images there
- Executor result parsing now tolerates model-produced string `checks` items and normalizes them into informational entries instead of failing the run parser

## Fastest Start

1. Copy `deploy/docker/.env.example` to `deploy/docker/.env`
2. Fill in at least:
   `ADO_BASE_URL`, `ADO_PROJECT`, `ADO_PAT`, `OPENAI_API_KEY`, `OPENCLAW_GATEWAY_TOKEN`, `OPENCLAW_HOOKS_TOKEN`, `HARNESS_INGRESS_TOKEN`, and `CODEX_MODEL`
3. Start the stack:

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

4. Optionally start the dashboard sidecar:

```sh
docker compose --profile bot-view --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

If you want the dashboard to be interactive, also set `HARNESS_CONTROL_TOKEN`.
If you only want read-only dashboard access, set `HARNESS_API_TOKEN` or `HARNESS_READONLY_TOKEN`.
When only `HARNESS_CONTROL_TOKEN` is configured, the sidecar read proxy now falls back to that token automatically.

5. Read the operational details in `deploy/README.md`

## Offline Mode

For air-gapped or lab environments, ClawHarness now supports a provider-local workflow:

- Switch `deploy/config/providers.yaml` to the `local-task` example
- Set `LOCAL_REPO_PATH`, `LOCAL_TASKS_PATH`, and `LOCAL_REVIEW_PATH`
- Trigger a run with a local task file instead of Azure DevOps or GitHub

Example:

```sh
python -m harness_runtime.main --provider-type local-task --task-id task-001
```

If `local-task.repository_path` is configured, `--repo-id` can be omitted.
The run will generate a local review markdown artifact under `.clawharness-review/` or `LOCAL_REVIEW_PATH`.

If you need a portable Docker package for an offline machine:

1. Export the deployment bundle:

```sh
python deploy/package/export_deploy_bundle.py --output dist/clawharness-deploy --force
```

2. On a connected machine, build or pull the images and save them:

```sh
docker save -o clawharness-images.tar \
  clawharness/openclaw-gateway:local \
  clawharness/harness-bridge:local \
  clawharness/openclaw-bot-view:local
```

3. Copy the bundle and `clawharness-images.tar` to the target machine, then run `load-images` followed by `up-offline`.

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
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
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
- merged PR -> run completed
- run completed -> provider task completion sync
- same-parent continuation after PR feedback and CI recovery, including child-run evidence

The main remaining gaps that still need broader live validation are:

- GitHub PR feedback and checks recovery in a real repository with live webhook delivery
- policy interaction in repositories with stricter protected-branch and review rules
- broader Linux native and non-local deployment validation
