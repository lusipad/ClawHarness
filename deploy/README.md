# ClawHarness 部署说明

## 部署与验证快照

当前已经完成真实验证的部分：

- Docker 栈：
  - `openclaw-gateway`
  - `clawharness-bridge`
  - `openclaw-bot-view`
- Azure DevOps task -> PR 主链路
- Azure PR feedback 恢复链路
- Azure CI recovery 自动修复与自动重试链路
- Windows self-hosted Azure agent 的 PowerShell 环境修复

当前仍未完成真实外部联调的部分：

- GitHub provider live webhook 验证
  - 当前原因：部署环境未提供 `GITHUB_TOKEN`
- Linux systemd 的更广泛真实部署覆盖

关键证据入口：

- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`

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

如果这次部署要改成 GitHub provider，还需要两步：

- 在 `deploy/config/providers.yaml` 中把 `task_pr_ci` 切换到注释里的 GitHub 配置
- 在 `.env` 中填写 `GITHUB_TOKEN`

3. 可选变量：

- `OPENAI_BASE_URL`：如使用 Codex 转发 endpoint 或自定义 OpenAI 兼容入口时填写
- `CODEX_REVIEW_MODEL`：如需把 review 模型固定为某个稳定值时填写
- `CODEX_REASONING_EFFORT`：如需统一默认推理强度时填写
- `ADO_WEBHOOK_SECRET`：启用 Azure DevOps webhook 校验时再填写
- `GITHUB_TOKEN`：切换到 GitHub provider 后必填
- `GITHUB_WEBHOOK_SECRET`：启用 GitHub webhook 校验时填写
- `RC_WEBHOOK_URL`：启用 Rocket.Chat 通知时再填写
- `RC_COMMAND_TOKEN`：启用 Rocket.Chat 入站命令 webhook 时填写
- `CODEX_HOME_DIR`：高级覆盖模式；如需复用自定义 Codex 配置或已有认证缓存时再设置
- `CODEX_CLI_VERSION`：高级覆盖模式；如需升级或回滚容器内的 Codex CLI 版本时填写；默认固定到当前已验证版本
- `HARNESS_IMAGE_MODEL`：如需把图片分析模型固定到专用多模态模型时填写；默认优先复用 `CODEX_REVIEW_MODEL`，再回退到 `CODEX_MODEL`

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

7. 如需同时启动 OpenClaw 可视化 dashboard，可额外启用 `bot-view` profile：

```sh
docker compose --profile bot-view --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

启动后可通过 `http://127.0.0.1:3001` 打开 sidecar 版 `OpenClaw-bot-review`。
如果要查看 ClawHarness 运行态页面，直接打开 `http://127.0.0.1:3001/clawharness`。
其中：

- `/` 仍然是 OpenClaw 的 bot / model / session 总览
- `/clawharness` 会通过 sidecar 内部代理读取 bridge 的只读 API，展示 ClawHarness 的 run、审计链、父子 run 图、checkpoint 和 artifact

### Docker 说明

- `openclaw-gateway` 镜像会在构建阶段把 `openclaw-plugin` 一并打包，并在首次启动时自动播种 `openclaw.json`。
- `openclaw-gateway` 与 `harness-bridge` 镜像都会默认安装官方 `@openai/codex` CLI，当前默认固定到 `0.118.0` 这个已验证版本。
- Docker 默认执行链路是：gateway 负责 OpenClaw Web UI、hooks 与持久化配置，bridge 直接在容器内调用 `codex exec` 执行工作项自动化；这样可以复用同一份 `.codex` 认证/配置卷，同时避开当前 OpenClaw ACPX 在非交互 Azure 自动化场景下的队列不稳定问题。
- 可选的 `openclaw-bot-view` sidecar 基于 `xmanrui/OpenClaw-bot-review` 固定提交构建，主要展示 OpenClaw 的 agent / session / gateway 视图；同时会叠加 ClawHarness overlay，因此除了原始首页外，还能通过 `/clawharness` 查看任务运行、状态汇总、审计链、父子 run 图以及恢复证据。
- compose 默认只把 `18789` 和 `8080` 绑定到 `127.0.0.1`，把本地管理面限制在宿主机回环地址。
- 如启用 `bot-view` profile，dashboard 默认绑定到 `127.0.0.1:3001`。
- Docker 默认模板会放行 `http://127.0.0.1:18789` 与 `http://localhost:18789` 访问 OpenClaw Control UI；如果你改成用域名或服务器 IP 打开 UI，再按需调整 gateway 的 `controlUi.allowedOrigins`。
- `harness-bridge` 与 `openclaw-gateway` 会共享同一份工作区挂载，保证 ACP 收到的 `cwd` 在两个容器内语义一致。
- `harness-bridge` 镜像已补齐 `git`、`node`、`npm`，可以覆盖当前 V1 编排里用到的 clone / branch / 基础本地检查能力。
- `harness-bridge` 还会挂载与 gateway 相同的 `CODEX_HOME_DIR`，直接复用 gateway 启动时生成的 `/home/node/.codex/config.toml` 与 `/home/node/.codex/auth.json`。
- `harness-bridge` 现在还会提供只读运行态 API：`/api/summary`、`/api/runs`、`/api/runs/<run_id>`、`/api/runs/<run_id>/audit`、`/api/runs/<run_id>/graph`。如果配置了 `HARNESS_INGRESS_TOKEN`，这些接口需要 `Authorization: Bearer <token>` 或 `x-harness-token`。
- `/api/runs/<run_id>/graph` 现在还会带出当前 run 和子 run 的 `skill_selections`，便于 bot-view 或审计面查看这次执行选择了哪些 skill、版本和触发原因。
- bridge 现在支持两条任务入口：`POST /webhooks/azure-devops` 与 `POST /webhooks/github`。GitHub webhook 优先使用 `X-Hub-Signature-256` + `GITHUB_WEBHOOK_SECRET` 验签。
- V2 Core 运行时现在会把 PR feedback 和 CI recovery 落成同一父 run 下的恢复子 run；每个子 run 都会记录自己的状态迁移、checkpoint、artifact 和审计事件。
- GitHub provider 目前支持 `issues` 的 `opened` / `reopened`、PR 上的 `issue_comment` / `pull_request_review_comment`，以及失败态 `check_run` / `check_suite` 事件。
- PR feedback / CI recovery 现在还会对同一父 run 做 single-flight 保护：同一时刻只允许一个同类型恢复链路占用该父 run 的 branch、workspace 与 session；follow-up 锁预算会自动对齐到 executor timeout 并额外预留缓冲。
- V2 child-run continuation 依赖 runtime orchestrator 模式；如果 bridge 以不带 `task_orchestrator` 的旧路径运行，PR / CI 事件会被显式拒绝，而不会静默退回旧的“覆写父 run”语义。
- 如启用 `bot-view` profile，建议明确设置 `HARNESS_READONLY_TOKEN`，让 bridge 的只读 API 与 webhook 写入口分离鉴权。
- sidecar 不应持有 `HARNESS_INGRESS_TOKEN`。它只应持有 `HARNESS_API_TOKEN` 或 `HARNESS_READONLY_TOKEN` 之一，并与 bridge 当前实际要求的只读 token 保持一致。
- 如果要启用 Rocket.Chat 入站命令，请同时配置 `RC_COMMAND_TOKEN`，并把 Rocket.Chat outgoing webhook 或 slash command 指向 `POST /webhooks/chat/rocketchat`。
- 入站命令支持 `status`、`detail`、`pause`、`resume`、`add-context`、`escalate`。
- 命令目标解析优先级是：显式 `run_id`，显式 `task_key`，已绑定对话线程。
- 推荐把命令 webhook 配成 `application/json`；当前也兼容 `application/x-www-form-urlencoded`。
- `add-context` 的文本和附件元数据会进入 run artifact，其中图片附件会记为 `chat-image`，为后续图片识别闭环保留统一工件入口。
- 如果 bridge 容器里提供了 `OPENAI_API_KEY`，图片附件会自动走 OpenAI 兼容 `responses` 接口分析，并把中文分析摘要写入 `image-analysis` artifact、checkpoint 与审计链。
- 默认工作区目录为 `OPENCLAW_WORKSPACE_DIR=./.data/workspace/harness`；如需改目录，可直接改 `deploy/docker/.env`。
- 默认推荐只维护少量稳定字段：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`CODEX_MODEL`、`CODEX_REVIEW_MODEL`、`CODEX_REASONING_EFFORT`。gateway 启动时会自动生成 `/home/node/.codex/config.toml` 和 `/home/node/.codex/auth.json`，所以新实例不需要再逐台执行 `codex login`。
- 如果你用的是 Codex 转发 endpoint，可以把转发地址写到 `OPENAI_BASE_URL`，把对应 key 写到 `OPENAI_API_KEY`。当前默认生成的是 OpenAI provider 兼容配置，不再把上游 `config.toml` 的全部原生字段暴露给部署方。
- `OPENAI_API_KEY` 必须与 `OPENAI_BASE_URL` 对应的上游服务匹配；如果 key 和 endpoint 不匹配，`codex` 调用会返回 `401 invalid_api_key`。
- `CODEX_HOME_DIR` 现在保留为高级逃生口；只有在你明确要接管内部 Codex 配置时才建议使用。只要 `.env` 里也提供了 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `CODEX_MODEL` 等稳定字段，启动脚本就会用这些值覆盖容器内的 Codex 配置。
- ClawHarness 自带的 skill registry 位于 `openclaw-plugin/skills/registry.json`。如果你要升级、回滚或审计 skill 版本，优先维护这一个文件，而不是在 prompt 模板里散落复制 skill 元数据。
- 如需做长期运行清理，可手工执行：

```sh
python -m harness_runtime.main --run-maintenance
```

- 如需覆盖默认保留期或单次清理批次，可追加：

```sh
python -m harness_runtime.main --run-maintenance --cleanup-retention-days 14 --cleanup-limit 100
```

- 在 Docker 下，推荐用以下方式周期执行 maintenance：

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml exec harness-bridge \
  python -m harness_runtime.main --run-maintenance
```

- maintenance 只会处理超过保留期的终态 run，并且只删除 `workspace_root` 下、且没有被活跃 run 复用的 workspace；run、audit、artifact 和 skill-selection 记录会继续保留用于审计。
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
- 如果 Azure DevOps Windows self-hosted agent 在脚本步骤里报出 `The following error occurred while loading the extended type data file` 或 `ConvertTo-SecureString ... module could not be loaded`，先不要急着改 pipeline。优先重启 agent，并从干净的 `cmd.exe` 会话启动：

```cmd
set "PSModulePath=C:\Program Files\WindowsPowerShell\Modules;C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules"
set "POWERSHELL_DISTRIBUTION_CHANNEL="
set "POWERSHELL_TELEMETRY_OPTOUT=1"
call D:\Tools\clawharness-ado-agent\run.cmd
```

- 上面的做法已经在本机真实验证通过：旧进程环境下失败的 build `40`，在重启 agent 后同类验证 build `41` 成功，随后完整 CI recovery 自动重试 build `43` 也成功。
