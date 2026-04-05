# ClawHarness Deployment Notes

## Docker

1. Copy `deploy/docker/.env.example` to `.env` and fill in the required secrets.
2. Start the stack with:

```sh
docker compose -f deploy/docker/compose.yml up --build -d
```

3. Verify the bridge and gateway:

```sh
sh deploy/scripts/healthcheck.sh
```

## Native Linux

1. Install OpenClaw and Python 3.
2. Copy the service files from `deploy/systemd/` into `/etc/systemd/system/`.
3. Provide environment files under `/etc/openclaw/` and `/etc/clawharness/`.
4. Enable and start:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw.service harness-bridge.service
```

## Native Windows

1. Install OpenClaw CLI, Python 3, and Node/npm.
2. Run `deploy/windows/install-openclaw.ps1`.
3. Run `deploy/windows/install-rocketchat-local.ps1` if you want a local Rocket.Chat workspace plus an auto-generated `RC_WEBHOOK_URL`.
4. Start the gateway in a terminal with `powershell -ExecutionPolicy Bypass -File deploy/windows/run-gateway.ps1`.
5. Start the bridge in another terminal with `powershell -ExecutionPolicy Bypass -File deploy/windows/run-harness.ps1`.
6. Verify with `deploy/scripts/healthcheck.ps1`.
7. Re-run Rocket.Chat capability checks with `powershell -ExecutionPolicy Bypass -File deploy/windows/verify-rocketchat-capabilities.ps1`.

Notes:
- `install-openclaw.ps1` links the local ClawHarness plugin, installs plugin runtime dependencies, and configures local loopback gateway + hooks.
- `install-rocketchat-local.ps1` starts a local Docker-based Rocket.Chat workspace on `http://127.0.0.1:3000`, creates channel `#ai-dev`, creates/reuses an incoming webhook integration, stores `RC_WEBHOOK_URL` as a user environment variable, and runs a webhook smoke test.
- The same script also persists `RC_ADMIN_USERNAME`, `RC_ADMIN_PASS`, `RC_ADMIN_EMAIL`, and `RC_ROOT_URL` as user environment variables so the local workspace can be reopened without rerunning setup.
- `verify-rocketchat-capabilities.ps1` live-checks group chat, direct message, and image delivery through the configured incoming webhook, then reports whether any OpenClaw-specific slash commands exist in the workspace.
- `run-gateway.ps1` starts the gateway via the installed Node runtime directly, avoiding PowerShell wrapper issues on some Windows setups.
- By default the Windows flow avoids Startup-folder persistence and hidden background launch because those patterns are more likely to trigger antivirus heuristics. Use `install-openclaw.ps1 -InstallGatewayLoginItem` only if you explicitly want a gateway login item.
- `run-harness.ps1` runs the bridge in the foreground and persists `HARNESS_INGRESS_TOKEN` as a user environment variable if missing.
- `ADO_PAT`, `ADO_WEBHOOK_SECRET`, and `RC_WEBHOOK_URL` remain optional until live Azure DevOps and Rocket.Chat integration is enabled.
