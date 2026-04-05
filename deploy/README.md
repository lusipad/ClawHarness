# ClawHarness 部署说明

## Docker

Docker 方案现在已经收敛为“单条命令启动服务栈”。前提是你先准备好 `deploy/docker/.env`。

1. 将 `deploy/docker/.env.example` 复制为 `deploy/docker/.env`。
2. 至少填写以下必需变量：

- `ADO_BASE_URL`
- `ADO_PROJECT`
- `ADO_PAT`
- `OPENCLAW_GATEWAY_TOKEN`
- `OPENCLAW_HOOKS_TOKEN`
- `HARNESS_INGRESS_TOKEN`
- `OPENAI_API_KEY`
- `CODEX_MODEL`

3. 可选变量：

- `OPENAI_BASE_URL`：如使用 Codex 转发 endpoint 或自定义 OpenAI 兼容入口时填写
- `CODEX_REVIEW_MODEL`：如需把 review 模型固定为某个稳定值时填写
- `CODEX_REASONING_EFFORT`：如需统一默认推理强度时填写
- `ADO_WEBHOOK_SECRET`：启用 Azure DevOps webhook 校验时再填写
- `RC_WEBHOOK_URL`：启用 Rocket.Chat 通知时再填写
- `CODEX_HOME_DIR`：高级覆盖模式；如需复用自定义 Codex 配置或已有认证缓存时再设置
- `CODEX_CLI_VERSION`：高级覆盖模式；如需升级或回滚容器内的 Codex CLI 版本时填写；默认固定到当前已验证版本

4. 一键启动服务栈：

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

5. 验证 bridge 与 gateway：

```sh
sh deploy/scripts/healthcheck.sh
```

6. 如需停止并清理容器：

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml down
```

### Docker 说明

- `openclaw-gateway` 镜像会在构建阶段把 `openclaw-plugin` 一并打包，并在首次启动时自动播种 `openclaw.json`。
- `openclaw-gateway` 与 `harness-bridge` 镜像都会默认安装官方 `@openai/codex` CLI，当前默认固定到 `0.118.0` 这个已验证版本。
- Docker 默认执行链路是：gateway 负责 OpenClaw Web UI、hooks 与持久化配置，bridge 直接在容器内调用 `codex exec` 执行工作项自动化；这样可以复用同一份 `.codex` 认证/配置卷，同时避开当前 OpenClaw ACPX 在非交互 Azure 自动化场景下的队列不稳定问题。
- compose 默认只把 `18789` 和 `8080` 绑定到 `127.0.0.1`，把本地管理面限制在宿主机回环地址。
- Docker 默认模板会放行 `http://127.0.0.1:18789` 与 `http://localhost:18789` 访问 OpenClaw Control UI；如果你改成用域名或服务器 IP 打开 UI，再按需调整 gateway 的 `controlUi.allowedOrigins`。
- `harness-bridge` 与 `openclaw-gateway` 会共享同一份工作区挂载，保证 ACP 收到的 `cwd` 在两个容器内语义一致。
- `harness-bridge` 镜像已补齐 `git`、`node`、`npm`，可以覆盖当前 V1 编排里用到的 clone / branch / 基础本地检查能力。
- `harness-bridge` 还会挂载与 gateway 相同的 `CODEX_HOME_DIR`，直接复用 gateway 启动时生成的 `/home/node/.codex/config.toml` 与 `/home/node/.codex/auth.json`。
- 默认工作区目录为 `OPENCLAW_WORKSPACE_DIR=./.data/workspace/harness`；如需改目录，可直接改 `deploy/docker/.env`。
- 默认推荐只维护少量稳定字段：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`CODEX_MODEL`、`CODEX_REVIEW_MODEL`、`CODEX_REASONING_EFFORT`。gateway 启动时会自动生成 `/home/node/.codex/config.toml` 和 `/home/node/.codex/auth.json`，所以新实例不需要再逐台执行 `codex login`。
- 如果你用的是 Codex 转发 endpoint，可以把转发地址写到 `OPENAI_BASE_URL`，把对应 key 写到 `OPENAI_API_KEY`。当前默认生成的是 OpenAI provider 兼容配置，不再把上游 `config.toml` 的全部原生字段暴露给部署方。
- `OPENAI_API_KEY` 必须与 `OPENAI_BASE_URL` 对应的上游服务匹配；如果 key 和 endpoint 不匹配，`codex` 调用会返回 `401 invalid_api_key`。
- `CODEX_HOME_DIR` 现在保留为高级逃生口；只有在你明确要接管内部 Codex 配置时才建议使用。只要 `.env` 里也提供了 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `CODEX_MODEL` 等稳定字段，启动脚本就会用这些值覆盖容器内的 Codex 配置。
- 首次启动完成后，通过 OpenClaw Web UI 对 gateway 配置做的修改会保留在 `OPENCLAW_DATA_DIR` 对应卷里，不会在普通重启时被模板覆盖。
- `harness-bridge` 会在每次启动时从 gateway 持久化配置中读取 gateway token、hooks token、hooks path 和 default session key，所以这几项 UI 改动在重启 bridge 后会自动生效。
- 如果你想重新用 `.env` 的默认值覆盖当前 UI 改动，可以把 `OPENCLAW_FORCE_RENDER_CONFIG=1` 启一次；覆盖完成后再改回 `0`。
- 如果你要发给别人一个独立部署目录，而不是整仓库，可以运行 `python deploy/package/export_deploy_bundle.py --output <目标目录>` 导出一个最小部署包。

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
