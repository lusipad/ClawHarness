# ClawHarness

English | [简体中文](README.zh-CN.md)

ClawHarness is an autonomous task-to-PR execution harness for Azure DevOps repositories. It connects Azure DevOps work items, OpenClaw ACP execution, local repository verification, branch and PR automation, and optional Rocket.Chat lifecycle notifications into one repeatable delivery loop.

## What It Does

- Uses a SQLite-backed runtime store for task claiming, deduplication, locking, and audit records
- Prepares an isolated workspace for each task run and creates a task branch
- Calls Codex through OpenClaw ACP to implement changes
- Runs local checks before commit and push
- Opens PRs automatically and keeps an audit trail for every run
- Supports webhook-driven continuation for PR feedback and CI failure recovery
- Ships deployment assets for Windows, Linux systemd, and Docker

## Repository Layout

- `ado_client/`: Azure DevOps REST client for work items, repositories, PRs, and builds
- `codex_acp_runner/`: ACP executor wrapper and structured result handling
- `harness_runtime/`: bridge service, orchestration logic, and runtime config loading
- `rocketchat_notifier/`: Rocket.Chat webhook notifier
- `run_store/`: SQLite schema and runtime persistence primitives
- `openclaw-plugin/`: OpenClaw plugin entry, hooks, flows, and skills
- `deploy/`: Docker, systemd, Windows, and config assets
- `.omx/plans/`: PRD, test spec, PDCA records, and validation evidence

## Current V1 Status

- The V1 happy path has been live-validated on Azure DevOps and OpenClaw ACP
- The real task-to-branch-to-PR loop is complete
- The PR feedback recovery loop has also been live-validated
- Evidence and PDCA records are stored under `.omx/plans/`

## Quick Start

1. Configure the required environment variables such as `ADO_BASE_URL`, `ADO_PROJECT`, `ADO_PAT`, `OPENCLAW_HOOKS_TOKEN`, and `OPENCLAW_GATEWAY_TOKEN`.
2. Review deployment options in `deploy/README.md`.
3. Run the Windows installer scripts or use the Docker/systemd assets for your target environment.
4. Run the automated checks:

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner harness_runtime rocketchat_notifier run_store tests
```

5. Trigger a manual task run:

```sh
python -m harness_runtime.main --task-id <work-item-id> --repo-id <repo-id>
```

## Validation Notes

The current implementation is strongest on the core V1 loop:

- task claim and dedupe
- ACP execution
- local check gate
- branch push
- PR creation
- same-run continuation after PR feedback

The main remaining gaps that still need broader live validation are:

- CI failure recovery and retry in a real build-backed project
- policy interaction in repositories with stricter protected-branch and review rules
- broader Docker and Linux native deployment validation
