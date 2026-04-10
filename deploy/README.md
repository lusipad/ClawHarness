# ClawHarness 部署说明

## 部署与验证快照

V3 的本地优先 / 插件化 / 可选 Shell 基线已经完成，并通过 architect 复核。
当前默认推荐路径是 `core-only + local-first`；OpenClaw Shell、bot-view、Azure DevOps、GitHub 都改为按需叠加。

当前已经完成真实验证的部分：

- Docker 栈：
  - `openclaw-gateway`
  - `clawharness-bridge`
  - `openclaw-bot-view`
- 离线 `local-task` Docker 主链路：
  - `task-002`
  - `manual-local-repo-task-002`
  - `refs/heads/ai/task-002-add-offline-validation-note`
  - 本地 commit `4cca6c1`
  - 本地 review artifact `local-0eedc568`
- 离线默认安全行为：
  - `LOCAL_PUSH_ENABLED=0` 时源仓库不变
  - 改动只落在隔离 workspace
- bot-view 控制面：
  - `/clawharness`
  - `Pause`
  - `Resume`
  - `Add Context`
- Azure DevOps task -> PR 主链路
- Azure PR feedback 恢复链路
- Azure CI recovery 自动修复与自动重试链路
- Azure PR merged -> run completed -> work item completed 自动收口链路
- Windows self-hosted Azure agent 的 PowerShell 环境修复
- GitHub live webhook 入口与 GitHub-backed run 创建
- GitHub 在 Windows 上的 issue -> PR stdin 重跑闭环：
  - issue `#7`
  - run `34a87604-6c44-4177-86b1-7676cb77f6cf`
  - PR `8`
- V3 默认部署与运行时基线：
  - `local-task` 默认 profile
  - `codex-cli` 默认 executor
  - `shell disabled` 默认运行
  - `task-provider` / `executor` / `notifier` manifest-driven registry

当前仍未完成真实外部联调的部分：

- GitHub PR feedback 与 checks recovery 在真实 webhook 仓库中的更广泛 live 验证
- Linux systemd 的更广泛真实部署覆盖

关键证据入口：

- `.omx/plans/prd-clawharness-v3-2026-04-09.md`
- `.omx/plans/test-spec-clawharness-v3-2026-04-09.md`
- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`

## Docker

Docker 现在默认收敛为“core-only + local-first”启动路径。前提是你先准备好 `deploy/docker/.env`。

Windows 下如果你希望更接近“一键安装”，优先使用：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key>
```

如果你更希望走简化后的交互式安装向导，可直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -Interactive
```

在交互式 PowerShell 里直接运行 `deploy/windows/bootstrap.ps1`，现在也会自动进入快速向导。
向导执行前会先展示安装摘要，执行完成后会自动跑一次安装检查。

如果你确实需要原生安装、更多目录项或完整高级参数，再使用：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -Interactive -Advanced
```

这个安装器现在支持三种模式：

- `-InstallMode docker`：绿色优先，默认推荐
- `-InstallMode native-core`：不依赖 Docker，也不依赖 OpenClaw
- `-InstallMode native-openclaw`：不依赖 Docker，但会配置本机 OpenClaw

如需启用 OpenClaw Shell：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key> -Profile shell
```

如需启用 bot-view：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key> -Profile bot-view
```

如果本机还没装 Docker Desktop，可追加：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key> -InstallDocker
```

如果你这次只想先生成 `.env`、目录和 token，不立即启动容器，可追加：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key> -SkipStart
```

如果你想顺手生成一个本地离线任务示例文件，可追加：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key> -CreateSampleTask
```

安装或配置完成后，可运行安装检查：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/check-install.ps1 -InstallMode docker
powershell -ExecutionPolicy Bypass -File deploy/windows/check-install.ps1 -InstallMode native-core
powershell -ExecutionPolicy Bypass -File deploy/windows/check-install.ps1 -InstallMode native-openclaw
```

如需同时检查本机服务是否真的已经启动，可追加 `-CheckRuntime`。

这个脚本会自动：

- 复制 `.env.example` 生成 `.env`
- 准备 `.data/` 下的本地仓库、任务、review、workspace 与持久化目录
- 生成 `HARNESS_INGRESS_TOKEN` 等随机 token
- 在需要时尝试拉起 Docker Desktop
- 按所选 profile 启动 compose 栈
- 默认保留已有 `.env` 中未显式覆盖的值，避免重复运行时把已有 provider 或 token 配置清空
- 在 `-SkipStart` 模式下只做安装准备，不强依赖 `docker` 在 PATH 中可用
- 如果检测到固定容器名已被旧栈占用，会明确提示“当前默认是单机单实例 Docker 栈”

原生模式额外说明：

- `native-core` 要求宿主机已有 `python`、`git`、`codex`
- `native-openclaw` 要求宿主机已有 `python`、`git`、`codex`、`node`、`npm`、`openclaw`
- 两种原生模式都会把必要配置写入用户级环境变量，便于重开终端后继续运行

1. 将 `deploy/docker/.env.example` 复制为 `deploy/docker/.env`。
2. 默认保持：

- `HARNESS_PROVIDER_PROFILE=local-task`
- `HARNESS_SHELL_ENABLED=0`
- `HARNESS_EXECUTOR_BACKEND=codex-cli`

3. local-first 最小必需变量：

- `OPENAI_API_KEY`
- `LOCAL_REPO_PATH`
- `LOCAL_TASKS_PATH`
- `LOCAL_REVIEW_PATH`

4. 如果这次部署要改成远端 provider：

- Azure DevOps：
  把 `HARNESS_PROVIDER_PROFILE` 改为 `azure-devops`，并填写 `ADO_BASE_URL`、`ADO_PROJECT`、`ADO_PAT`
- GitHub：
  把 `HARNESS_PROVIDER_PROFILE` 改为 `github`，并填写 `GITHUB_TOKEN`

5. 如果这次部署还要启用 OpenClaw Shell：

- 把 `HARNESS_SHELL_ENABLED=1`
- 填写 `OPENCLAW_GATEWAY_TOKEN`
- 填写 `OPENCLAW_HOOKS_TOKEN`

6. 其余可选变量：

- `OPENAI_BASE_URL`：如使用 Codex 转发 endpoint 或自定义 OpenAI 兼容入口时填写
- `CODEX_REVIEW_MODEL`：如需把 review 模型固定为某个稳定值时填写
- `CODEX_REASONING_EFFORT`：如需统一默认推理强度时填写
- `ADO_WEBHOOK_SECRET`：启用 Azure DevOps webhook 校验时再填写
- `GITHUB_TOKEN`：切换到 GitHub provider 后必填
- `GITHUB_WEBHOOK_SECRET`：启用 GitHub webhook 校验时填写
- `RC_WEBHOOK_URL`：启用 Rocket.Chat 通知时再填写
- `RC_COMMAND_TOKEN`：启用 Rocket.Chat 入站命令 webhook 时填写
- `LOCAL_REPO_DIR`：Docker 挂载到 `/mnt/local-repo` 的宿主机目录，离线 `local-task` 模式下使用
- `LOCAL_TASKS_DIR`：Docker 挂载到 `/mnt/local-tasks` 的宿主机目录，存放本地任务文件
- `LOCAL_REVIEW_DIR`：Docker 挂载到 `/mnt/local-reviews` 的宿主机目录，存放本地 review 工件
- `LOCAL_REPO_PATH`：容器内本地仓库路径，默认 `/mnt/local-repo`
- `LOCAL_TASKS_PATH`：容器内本地任务目录，默认 `/mnt/local-tasks`
- `LOCAL_REVIEW_PATH`：容器内本地 review 目录，默认 `/mnt/local-reviews`
- `LOCAL_BASE_BRANCH`：离线本地仓库默认基线分支；留空时自动检测当前分支
- `LOCAL_PUSH_ENABLED`：是否允许 `local-task` 在本地 provider 下执行 `git push`；默认 `0`
- `CODEX_HOME_DIR`：高级覆盖模式；如需复用自定义 Codex 配置或已有认证缓存时再设置
- `CODEX_CLI_VERSION`：高级覆盖模式；如需升级或回滚容器内的 Codex CLI 版本时填写；默认固定到当前已验证版本
- `HARNESS_IMAGE_MODEL`：如需把图片分析模型固定到专用多模态模型时填写；默认优先复用 `CODEX_REVIEW_MODEL`，再回退到 `CODEX_MODEL`
- `HARNESS_API_TOKEN`：如需让 bot-view 只拿只读 token 时填写
- `HARNESS_READONLY_TOKEN`：如需把 bridge 的只读 API 与写入口分离时填写
- `HARNESS_CONTROL_TOKEN`：如需启用 bot-view 控制动作或独立控制面时填写

7. 启动 core-only 服务栈：

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

8. 验证运行状态：

```sh
sh deploy/scripts/healthcheck.sh
```

9. 如需停止并清理容器：

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml down
```

10. 如需启用 OpenClaw Shell，可额外启用 `shell` profile：

```sh
docker compose --profile shell --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

11. 如需同时启动 OpenClaw 可视化 dashboard，可额外启用 `shell` + `bot-view`：

```sh
docker compose --profile shell --profile bot-view --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

启动后可通过 `http://127.0.0.1:3001` 打开 sidecar 版 `OpenClaw-bot-review`。
如果要查看 ClawHarness 运行态页面，直接打开 `http://127.0.0.1:3001/clawharness`。
其中：

- `/` 仍然是 OpenClaw 的 bot / model / session 总览
- `/clawharness` 会通过 sidecar 内部代理读取 bridge 的运行态 API，展示 ClawHarness 的 run、审计链、父子 run 图、checkpoint 和 artifact
- `/clawharness` 现在还会聚合 `pr_completed`、`task_completion_synced`、`task_completion_sync_failed`，并额外汇总人工干预态势、最近操作、上下文补充和图片识别结果
- `/clawharness` 现在还提供 `Pause`、`Resume`、`Escalate`、`Add Context` 控制区

### Docker 说明

- `openclaw-gateway` 现在是可选的 `shell` profile，而不是默认硬依赖。
- `openclaw-gateway` 镜像会在构建阶段把 `openclaw-plugin` 一并打包，并在首次启动时自动播种 `openclaw.json`。
- `openclaw-gateway` 与 `harness-bridge` 镜像都会默认安装官方 `@openai/codex` CLI，当前默认固定到 `0.118.0` 这个已验证版本。
- 当前 compose 仍使用固定 `container_name`，因此默认是“单机单实例”部署；如果本机已经有另一套 `clawharness-bridge` / `openclaw-gateway` / `openclaw-bot-view` 容器，先停掉旧栈再启动新栈。
- Docker 默认执行链路现在是：bridge 直接在容器内调用 `codex exec` 执行工作项自动化；OpenClaw Shell 只在你显式启用 `shell` profile 时叠加为 UI/chat 宿主。
- 可选的 `openclaw-bot-view` sidecar 基于 `xmanrui/OpenClaw-bot-review` 固定提交构建，主要展示 OpenClaw 的 agent / session / gateway 视图；同时会叠加 ClawHarness overlay，因此除了原始首页外，还能通过 `/clawharness` 查看任务运行、状态汇总、审计链、父子 run 图以及恢复证据。
- `/clawharness` 现在还会把审计链中的 PR 合并闭环事件汇总成状态卡，并派生出“当前能否暂停/恢复/升级、最近由谁干预、最近补充了什么上下文”的控制态势。
- compose 默认只把 `8080` 绑定到 `127.0.0.1`；如果启用了 `shell`，则 `18789` 也会绑定到 `127.0.0.1`。
- 如启用 `shell` + `bot-view`，dashboard 默认绑定到 `127.0.0.1:3001`。
- Docker 默认模板会放行 `http://127.0.0.1:18789` 与 `http://localhost:18789` 访问 OpenClaw Control UI；如果你改成用域名或服务器 IP 打开 UI，再按需调整 gateway 的 `controlUi.allowedOrigins`。
- `harness-bridge` 与 `openclaw-gateway` 会共享同一份工作区挂载，保证 ACP 收到的 `cwd` 在两个容器内语义一致。
- `harness-bridge` 镜像已补齐 `git`、`node`、`npm`，可以覆盖当前 V1 编排里用到的 clone / branch / 基础本地检查能力。
- `harness-bridge` 还会挂载与 gateway 相同的 `CODEX_HOME_DIR`，直接复用 gateway 启动时生成的 `/home/node/.codex/config.toml` 与 `/home/node/.codex/auth.json`。
- `harness-bridge` 现在还会额外挂载本地离线路径：
  `LOCAL_REPO_DIR -> /mnt/local-repo`、`LOCAL_TASKS_DIR -> /mnt/local-tasks`、`LOCAL_REVIEW_DIR -> /mnt/local-reviews`。
- `harness-bridge` 现在还会提供运行态 API：`/api/summary`、`/api/runs`、`/api/runs/<run_id>`、`/api/runs/<run_id>/audit`、`/api/runs/<run_id>/graph`，以及受控写入口 `POST /api/runs/<run_id>/command`。
- 只读 GET 接口允许 `HARNESS_READONLY_TOKEN`、`HARNESS_CONTROL_TOKEN` 或 `HARNESS_INGRESS_TOKEN` 访问；控制 POST 接口优先要求 `HARNESS_CONTROL_TOKEN`，未设置时回退到 `HARNESS_INGRESS_TOKEN`。
- `/api/runs/<run_id>/graph` 现在还会带出当前 run 和子 run 的 `skill_selections`，便于 bot-view 或审计面查看这次执行选择了哪些 skill、版本和触发原因。
- bridge 现在支持两条任务入口：`POST /webhooks/azure-devops` 与 `POST /webhooks/github`。GitHub webhook 优先使用 `X-Hub-Signature-256` + `GITHUB_WEBHOOK_SECRET` 验签。
- V2 Core 运行时现在会把 PR feedback 和 CI recovery 落成同一父 run 下的恢复子 run；每个子 run 都会记录自己的状态迁移、checkpoint、artifact 和审计事件。
- provider 侧 PR 合并事件现在统一归一化成 `pr.merged`，bridge 收到后会自动把根 run 置为 `completed`。
- run 自动收口后，bridge 会继续尝试回写 provider 侧任务状态；Azure DevOps 优先写 `Done`，失败回退 `Closed`；GitHub 会关闭对应 issue。
- 如果任务回写失败，bridge 不会回滚已完成的 run，而是记录 `task_completion_sync_failed` 审计事件，保证主闭环稳定。
- GitHub provider 目前支持 `issues` 的 `opened` / `reopened`、PR 上的 `issue_comment` / `pull_request_review_comment`，以及失败态 `check_run` / `check_suite` 事件。
- PR feedback / CI recovery 现在还会对同一父 run 做 single-flight 保护：同一时刻只允许一个同类型恢复链路占用该父 run 的 branch、workspace 与 session；follow-up 锁预算会自动对齐到 executor timeout 并额外预留缓冲。
- V2 child-run continuation 依赖 runtime orchestrator 模式；如果 bridge 以不带 `task_orchestrator` 的旧路径运行，PR / CI 事件会被显式拒绝，而不会静默退回旧的“覆写父 run”语义。
- 如启用 `bot-view` profile，推荐至少设置 `HARNESS_CONTROL_TOKEN`。
- 如果你想做严格分权，可把 sidecar 的只读访问设置为 `HARNESS_API_TOKEN` 或 `HARNESS_READONLY_TOKEN`，把交互控制设置为 `HARNESS_CONTROL_TOKEN`。
- sidecar 不应持有 `HARNESS_INGRESS_TOKEN`。当前 sidecar 读代理会按 `HARNESS_API_TOKEN -> HARNESS_READONLY_TOKEN -> HARNESS_CONTROL_TOKEN` 的顺序取 token。
- 如果要启用 Rocket.Chat 入站命令，请同时配置 `RC_COMMAND_TOKEN`，并把 Rocket.Chat outgoing webhook 或 slash command 指向 `POST /webhooks/chat/rocketchat`。
- 如果要启用 Weixin 入站命令，请把你的 Weixin 适配层指向 `POST /webhooks/chat/weixin`，并在 payload 中附带与 `RC_COMMAND_TOKEN` 相同语义的 `token`。
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
- ClawHarness 的 canonical skill registry 位于 `skills/core/registry.json`。如果你要升级、回滚或审计 skill 版本，优先维护 canonical source，而不是直接手工改 `openclaw-plugin/skills/registry.json`。
- `openclaw-plugin/skills/` 是从 canonical source 投影出来的兼容镜像。变更 `skills/core/` 后，重新运行 `python -m harness_runtime.skill_projection`；如需校验没有漂移，可运行 `python -m harness_runtime.skill_projection --check`。
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
- 启用 `shell` 后，通过 OpenClaw Web UI 对 gateway 配置做的修改会保留在 `OPENCLAW_DATA_DIR` 对应卷里，不会在普通重启时被模板覆盖。
- `harness-bridge` 在 `HARNESS_SHELL_ENABLED=1` 时会优先从 gateway 持久化配置中读取 gateway token、hooks token、hooks path 和 default session key。
- 如果你想重新用 `.env` 的默认值覆盖当前 UI 改动，可以把 `OPENCLAW_FORCE_RENDER_CONFIG=1` 启一次；覆盖完成后再改回 `0`。
- 如果你要发给别人一个独立部署目录，而不是整仓库，可以运行 `python deploy/package/export_deploy_bundle.py --output <目标目录>` 导出一个最小部署包。

### 本地离线任务模式

如果你希望不依赖 Azure DevOps / GitHub，而是在本机或隔离环境里做完整闭环，直接使用默认 `deploy/config/providers.yaml`，并填写：

- `LOCAL_REPO_PATH`
- `LOCAL_TASKS_PATH`
- `LOCAL_REVIEW_PATH`
- `LOCAL_BASE_BRANCH`
- `LOCAL_PUSH_ENABLED`

当前 `local-task` 的闭环定义是：

- 读取本地任务文件
- clone 本地仓库到隔离 workspace
- 创建本地任务分支
- 本地提交
- 生成本地 review markdown 工件

它不会伪造 Azure DevOps 或 GitHub 的远端 PR，也不会伪造远端 CI。

本地手工触发示例：

```sh
python -m harness_runtime.main --provider-type local-task --task-id task-001
```

如果 `providers.yaml` 中已经配置了 `repository_path`，则可以不传 `--repo-id`。
如果想显式指定另一个本地仓库：

```sh
python -m harness_runtime.main --provider-type local-task --task-id task-001 --repo-id D:/Repos/example-repo
```

本地 review 工件默认会写入 `LOCAL_REVIEW_PATH/pull-requests/`，任务状态与评论会分别写入 `task-state/`、`task-comments/`。

如果你要切到远端 provider，可改用：

- `deploy/config/providers.azure-devops.yaml`
- `deploy/config/providers.github.yaml`

## 离线部署

如果目标机器不能联网构建镜像，推荐使用“导出部署包 + 导出镜像”的方式：

1. 在源码仓库导出部署包：

```sh
python deploy/package/export_deploy_bundle.py --output dist/clawharness-deploy --force
```

2. 在有网机器构建或拉取镜像后导出：

```sh
docker save -o clawharness-images.tar \
  clawharness/openclaw-gateway:local \
  clawharness/harness-bridge:local \
  clawharness/openclaw-bot-view:local
```

3. 将 `dist/clawharness-deploy` 与 `clawharness-images.tar` 一起复制到目标机器。
4. 在目标机器先导入镜像：

```powershell
./load-images.ps1
```

或：

```sh
./load-images.sh
```

5. 再离线启动：

```powershell
./up-offline.ps1
```

或：

```sh
./up-offline.sh
```

如果还要启用 OpenClaw Shell：

```powershell
./up-offline.ps1 -Shell
```

或：

```sh
./up-offline.sh --shell
```

如果还要启动 `bot-view` sidecar：

```powershell
./up-offline.ps1 -BotView
```

或：

```sh
./up-offline.sh --bot-view
```

默认的 `up.ps1` / `up.sh` 会带 `--build`，适合在线环境；完全离线部署时不要用它们。

## GitHub Actions 安装包

如果你希望每次合并或打 tag 后，GitHub Actions 自动产出可下载的安装包，仓库已经内置了 [`.github/workflows/package-installers.yml`](../.github/workflows/package-installers.yml)。

这个 workflow 的默认行为是：

- `push` 到 `main`：产出在线安装包 artifact
- `push` 匹配 `v*` 的 tag：产出带版本标签的在线安装包、自动附带离线镜像归档，并同步发布到对应 GitHub Release
- `workflow_dispatch`：可手工触发；当 `include_offline_images=true` 时，会额外构建离线 Docker 镜像归档

artifact 内容包括：

- `clawharness-deploy-<label>.zip`
- `SHA256SUMS-<label>.txt`
- `artifact-manifest-<label>.json`
- `clawharness-images-<label>.tar.gz`
  在 `v*` tag 发布或手工触发并启用 `include_offline_images=true` 时附带

如果你要在本地先验证这条打包链路，可执行：

```sh
python deploy/package/package_release_assets.py --output dist/github-actions --label local --force
```

如果本地已经准备好了离线镜像归档，再执行：

```sh
python deploy/package/package_release_assets.py --output dist/github-actions --label local --image-archive clawharness-images.tar --force
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

推荐优先使用统一安装器：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -InstallMode native-core -OpenAiApiKey <your-key>
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -InstallMode native-openclaw -OpenAiApiKey <your-key>
```

如果你要手工执行，分两条路径：

### Windows 原生 core-only

1. 安装 `Python 3`、`Git`、`Codex CLI`。
2. 配置用户级环境变量：`OPENAI_API_KEY`、`LOCAL_REPO_PATH`、`LOCAL_TASKS_PATH`、`LOCAL_REVIEW_PATH`。
3. 启动 bridge：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/run-harness-core.ps1
```

### Windows 原生 OpenClaw

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
- `bootstrap.ps1` 现在可以直接在 Docker、原生 core-only、原生 OpenClaw 三条路径之间切换，避免维护多套安装入口。
- `check-install.ps1` 会按当前安装模式检查命令依赖、关键环境变量、关键路径，以及可选的 health endpoint。
- `install-rocketchat-local.ps1` 会在 `http://127.0.0.1:3000` 启动基于 Docker 的本地 Rocket.Chat 工作区，创建 `#ai-dev` 频道，创建或复用 incoming webhook 集成，并把 `RC_WEBHOOK_URL` 保存为用户级环境变量。
- 同一个脚本还会把 `RC_ADMIN_USERNAME`、`RC_ADMIN_PASS`、`RC_ADMIN_EMAIL`、`RC_ROOT_URL` 保存为用户级环境变量，便于后续重开本地工作区。
- `verify-rocketchat-capabilities.ps1` 会真实检查群聊、私聊、图片投递能力，并报告工作区中是否存在 OpenClaw 专用 slash command。
- `run-gateway.ps1` 通过已安装的 Node 运行时直接启动 gateway，避免部分 Windows 环境下 PowerShell 包装层带来的问题。
- 默认 Windows 流程不会使用“启动目录常驻”或“隐藏后台启动”，因为这些模式更容易触发杀毒软件启发式拦截。只有在你明确需要时，才使用 `install-openclaw.ps1 -InstallGatewayLoginItem`。
- `run-harness-core.ps1` 会以前台方式运行不依赖 OpenClaw 的 core-only bridge。
- `run-harness.ps1` 会以前台方式运行 OpenClaw 增强 bridge；如果缺失 `HARNESS_INGRESS_TOKEN`，它会自动生成并保存为用户级环境变量。
- `run-harness-core.ps1` 与 `run-harness.ps1` 现在都会根据 `HARNESS_PROVIDER_PROFILE` 自动选择 `providers.yaml` / `providers.azure-devops.yaml` / `providers.github.yaml`。
- Windows + GitHub 的 issue -> PR stdin 重跑链路已经在真实仓库完成过一次 live 验证；只要 `GITHUB_TOKEN` 已配置，就可以用一个小型文档任务复现同样的验证路径。
- GitHub 的 PR feedback 与 checks recovery 仍建议在你自己的真实 webhook 仓库里再跑一轮验收，不要把这两段链路提前宣称为已全面 live close。
- `ADO_PAT`、`ADO_WEBHOOK_SECRET`、`RC_WEBHOOK_URL` 在未启用真实 Azure DevOps / Rocket.Chat 联动前可以暂时留空。
- 如果 Azure DevOps Windows self-hosted agent 在脚本步骤里报出 `The following error occurred while loading the extended type data file` 或 `ConvertTo-SecureString ... module could not be loaded`，先不要急着改 pipeline。优先重启 agent，并从干净的 `cmd.exe` 会话启动：

```cmd
set "PSModulePath=C:\Program Files\WindowsPowerShell\Modules;C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules"
set "POWERSHELL_DISTRIBUTION_CHANNEL="
set "POWERSHELL_TELEMETRY_OPTOUT=1"
call D:\Tools\clawharness-ado-agent\run.cmd
```

- 上面的做法已经在本机真实验证通过：旧进程环境下失败的 build `40`，在重启 agent 后同类验证 build `41` 成功，随后完整 CI recovery 自动重试 build `43` 也成功。
