# ClawHarness

English | [简体中文](README.zh-CN.md)

ClawHarness is a local-first autonomous task-to-PR execution harness. It can run as a lightweight core against local repositories and local task files, then layer Azure DevOps, GitHub, OpenClaw Shell, chat, and bot-view on top when you need them.

## What It Does

- Uses a SQLite-backed runtime store for task claiming, deduplication, locking, and audit records
- Prepares an isolated workspace for each task run and creates a task branch
- Calls Codex through the local Codex CLI by default, with optional OpenClaw Shell integration
- Runs local checks before commit and push
- Opens PRs automatically and keeps an audit trail for every run
- Supports webhook-driven continuation for PR feedback and CI failure recovery
- Supports provider-neutral routing across Azure DevOps and GitHub
- Supports an offline `local-task` mode for local repositories, local task files, and local review artifacts
- Ships exportable deployment bundles with `load-images` and `up-offline` scripts for air-gapped environments
- Includes a GitHub Actions packaging workflow that publishes installer artifacts and can optionally attach an offline image archive
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

- `docs/system-architecture.md`: V3 system architecture overview, runtime layering, and deployment topology
- `deploy/README.md`: deployment options, configuration, and operations notes
- `docs/plugin-architecture.md`: plugin, skill, workflow, and runtime boundary summary
- `docs/plugin-boundary.md`: ownership and maintenance boundary rules
- `docs/plugin-skill-workflow-boundary.md`: detailed skill/workflow/capability boundary notes
- `skills/README.md`: canonical skill ownership and projection notes
- `.omx/plans/prd-clawharness-v3-2026-04-09.md`: V3 local-first / pluginized / lightweight product definition
- `.omx/plans/test-spec-clawharness-v3-2026-04-09.md`: V3 acceptance criteria and verification gates
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`: V2 product definition and scope
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`: V2 acceptance criteria and validation gates
- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`: latest live-validation evidence snapshot
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`: V1 live-validation history and PDCA evidence

## Current Status

- Latest local verification:
  `python -m unittest discover -s tests -v` -> `175/175` passed
- Latest structural verification:
  `python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests deploy/package deploy/windows` -> passed
- V3 local-first / pluginized / optional-shell baseline is complete and architect-approved
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

- Use the Docker core-only stack as the default deployment path
- Keep `HARNESS_PROVIDER_PROFILE=local-task` unless you explicitly want Azure DevOps or GitHub
- Turn on `--profile shell` only if you need OpenClaw UI, chat hosting, or bot-view
- Turn on `--profile shell --profile bot-view` if you want the dashboard sidecar
- If you enable interactive bot-view controls, set `HARNESS_CONTROL_TOKEN`; set `HARNESS_API_TOKEN` or `HARNESS_READONLY_TOKEN` only if you want a stricter read/write split
- Treat Azure DevOps as the most broadly live-validated remote provider path today

## Current Delivery

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

On Windows, the shortest path is:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key>
```

If you prefer the simplified interactive installer, run:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -Interactive
```

Running `deploy/windows/bootstrap.ps1` in an interactive PowerShell session without arguments now also opens the quick wizard automatically.
The wizard now shows an install summary before applying changes and runs a final install check automatically when bootstrap finishes.

If you need the full advanced wizard with native-install and extra directory options, run:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -Interactive -Advanced
```

The unified installer also supports:
`-InstallMode docker`, `-InstallMode native-core`, and `-InstallMode native-openclaw`.
If Docker Desktop is not installed yet, add `-InstallDocker`.
If you only want to prepare `.env`, data directories, and tokens without starting containers yet, add `-SkipStart`.
If you want a seeded local task file for a first offline run, add `-CreateSampleTask`.
After install or configuration, you can verify the current mode with:

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/check-install.ps1 -InstallMode docker
```

Switch `docker` to `native-core` or `native-openclaw` if you deployed one of those native modes.
The default Docker packaging is currently single-stack-per-host because the compose file uses fixed container names.

1. Copy `deploy/docker/.env.example` to `deploy/docker/.env`
2. Leave `HARNESS_PROVIDER_PROFILE=local-task`
3. Fill in at least:
   `OPENAI_API_KEY`, `LOCAL_REPO_PATH`, `LOCAL_TASKS_PATH`, and `LOCAL_REVIEW_PATH`
4. Start the core-only stack:

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

5. If you want OpenClaw Shell as an optional UI/chat layer:

```sh
docker compose --profile shell --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

6. If you also want the dashboard sidecar:

```sh
docker compose --profile shell --profile bot-view --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

If you want the dashboard to be interactive, also set `HARNESS_CONTROL_TOKEN`.
If you only want read-only dashboard access, set `HARNESS_API_TOKEN` or `HARNESS_READONLY_TOKEN`.
When only `HARNESS_CONTROL_TOKEN` is configured, the sidecar read proxy now falls back to that token automatically.

7. Read the operational details in `deploy/README.md`

## Offline Mode

For air-gapped or lab environments, ClawHarness now defaults to the provider-local workflow:

- Keep `deploy/config/providers.yaml` as-is
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

On Windows deployment bundles, you can also run:

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key>
```

Then verify the copied bundle with:

```powershell
./check-install.ps1 -InstallMode docker
```

## GitHub Actions Packaging

The repository now includes [`.github/workflows/package-installers.yml`](.github/workflows/package-installers.yml) for CI-produced installer artifacts.

- Pushes to `main` and tags matching `v*` generate the online installer bundle artifact.
- Tags matching `v*` also build the offline Docker image archive automatically and publish the packaged files to the GitHub Release for that tag.
- Manual `workflow_dispatch` runs can set `include_offline_images=true` to also build and attach the offline Docker image archive.
- The packaging step emits:
  `clawharness-deploy-<label>.zip`,
  `SHA256SUMS-<label>.txt`,
  `artifact-manifest-<label>.json`,
  and, when requested, `clawharness-images-<label>.tar`.

If you want to reproduce the same packaging flow locally:

```sh
python deploy/package/package_release_assets.py --output dist/github-actions --label local --force
python deploy/package/package_release_assets.py --output dist/github-actions --label local --image-archive clawharness-images.tar --force
```

## Quick Start

1. Configure the required environment variables for your task provider.
   For local-first, keep the default `deploy/config/providers.yaml`.
   For Azure DevOps, use `deploy/config/providers.azure-devops.yaml` or set `HARNESS_PROVIDER_PROFILE=azure-devops`.
   For GitHub, use `deploy/config/providers.github.yaml` or set `HARNESS_PROVIDER_PROFILE=github`.
   Only shell-enabled deployments need `OPENCLAW_HOOKS_TOKEN` and `OPENCLAW_GATEWAY_TOKEN`.
2. Review deployment options in `deploy/README.md`.
3. Run the Windows installer scripts or use the Docker/systemd assets for your target environment.
4. Run the automated checks:

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
```

5. Trigger a manual task run:

```sh
python -m harness_runtime.main --provider-type local-task --task-id <task-id>
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
