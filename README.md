# ClawHarness

ClawHarness is an autonomous task-to-PR harness for Azure DevOps repositories. It connects Azure DevOps work items, OpenClaw ACP execution, local verification, branch and PR automation, and optional Rocket.Chat lifecycle notifications into one repeatable delivery loop.

## What It Does

- Claims and deduplicates task runs in a SQLite-backed runtime store
- Prepares Azure DevOps repositories in isolated workspaces and creates task branches
- Dispatches implementation work to Codex through OpenClaw ACP
- Runs local pre-PR checks before commit and push
- Opens pull requests and records an audit trail for every run
- Supports webhook-driven continuation for PR feedback and CI recovery
- Ships deployment assets for Windows, Linux systemd, and Docker

## Repository Layout

- `ado_client/`: Azure DevOps REST client for work items, repositories, pull requests, and builds
- `codex_acp_runner/`: ACP runner and structured executor result handling
- `harness_runtime/`: bridge server, orchestration logic, and runtime config loading
- `rocketchat_notifier/`: Rocket.Chat webhook notifier
- `run_store/`: SQLite schema and runtime persistence primitives
- `openclaw-plugin/`: OpenClaw plugin entry, hooks, flows, and skills
- `deploy/`: Docker, systemd, Windows, and config assets
- `.omx/plans/`: PRD, test spec, PDCA notes, and evidence snapshots

## Current V1 Status

- The V1 happy path has been live-validated against Azure DevOps and OpenClaw ACP
- A real task-to-branch-to-PR loop was completed and documented on `2026-04-05`
- Evidence is captured in `.omx/plans/`

## Quick Start

1. Configure the required environment variables such as `ADO_BASE_URL`, `ADO_PROJECT`, `ADO_PAT`, `OPENCLAW_HOOKS_TOKEN`, and `OPENCLAW_GATEWAY_TOKEN`.
2. Review deployment options in `deploy/README.md`.
3. Run the Windows installer scripts or the Docker/systemd assets for your target environment.
4. Run the automated checks:

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner harness_runtime rocketchat_notifier run_store tests
```

5. For a manual task run, execute:

```sh
python -m harness_runtime.main --task-id <work-item-id> --repo-id <repo-id>
```

## Validation Notes

The current implementation is strongest on the core V1 path:

- task claim and dedupe
- ACP execution
- local check gate
- branch push
- PR creation

PR feedback resume, CI retry loops, and governed-repository policy enforcement are designed and locally tested, but still need broader live validation.
