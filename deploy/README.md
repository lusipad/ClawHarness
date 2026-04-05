# ClawHarness 部署说明

## Docker

1. 将 `deploy/docker/.env.example` 复制为 `.env`，并填写必需的密钥。
2. 启动服务栈：

```sh
docker compose -f deploy/docker/compose.yml up --build -d
```

3. 验证 bridge 与 gateway：

```sh
sh deploy/scripts/healthcheck.sh
```

## Linux 原生部署

1. 安装 OpenClaw 与 Python 3。
2. 将 `deploy/systemd/` 下的 service 文件复制到 `/etc/systemd/system/`。
3. 在 `/etc/openclaw/` 和 `/etc/clawharness/` 下准备环境变量文件。
4. 启用并启动服务：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw.service harness-bridge.service
```

## Windows 原生部署

1. 安装 OpenClaw CLI、Python 3 和 Node/npm。
2. 运行 `deploy/windows/install-openclaw.ps1`。
3. 如果需要本地 Rocket.Chat 工作区以及自动生成的 `RC_WEBHOOK_URL`，运行 `deploy/windows/install-rocketchat-local.ps1`。
4. 在一个终端中启动 gateway：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/run-gateway.ps1
```

5. 在另一个终端中启动 bridge：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/run-harness.ps1
```

6. 使用 `deploy/scripts/healthcheck.ps1` 验证运行状态。
7. 如需重新验证 Rocket.Chat 能力，运行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/verify-rocketchat-capabilities.ps1
```

## 说明

- `install-openclaw.ps1` 会链接本地 ClawHarness 插件、安装插件运行时依赖，并配置本地 loopback gateway 与 hooks。
- `install-rocketchat-local.ps1` 会在 `http://127.0.0.1:3000` 启动基于 Docker 的本地 Rocket.Chat 工作区，创建 `#ai-dev` 频道，创建或复用 incoming webhook 集成，并把 `RC_WEBHOOK_URL` 保存为用户级环境变量。
- 同一个脚本还会把 `RC_ADMIN_USERNAME`、`RC_ADMIN_PASS`、`RC_ADMIN_EMAIL`、`RC_ROOT_URL` 保存为用户级环境变量，便于后续重开本地工作区。
- `verify-rocketchat-capabilities.ps1` 会真实检查群聊、私聊、图片投递能力，并报告工作区中是否存在 OpenClaw 专用 slash command。
- `run-gateway.ps1` 通过已安装的 Node 运行时直接启动 gateway，避免部分 Windows 环境下 PowerShell 包装层带来的问题。
- 默认 Windows 流程不会使用“启动目录常驻”或“隐藏后台启动”，因为这些模式更容易触发杀毒软件启发式拦截。只有在你明确需要时，才使用 `install-openclaw.ps1 -InstallGatewayLoginItem`。
- `run-harness.ps1` 会以前台方式运行 bridge；如果缺失 `HARNESS_INGRESS_TOKEN`，它会自动生成并保存为用户级环境变量。
- `ADO_PAT`、`ADO_WEBHOOK_SECRET`、`RC_WEBHOOK_URL` 在未启用真实 Azure DevOps / Rocket.Chat 联动前可以暂时留空。
