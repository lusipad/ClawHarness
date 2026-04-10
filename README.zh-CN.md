# ClawHarness

[English](README.md) | 简体中文

ClawHarness 是一个本地优先的自主化任务到 PR 执行闭环。它可以先以轻量 core 形态跑本地仓库和本地任务文件，再按需叠加 Azure DevOps、GitHub、OpenClaw Shell、聊天与 bot-view。

## 功能概览

- 使用基于 SQLite 的运行时存储完成任务认领、去重、加锁和审计
- 为每次任务运行准备隔离工作区，并创建任务分支
- 默认通过本地 Codex CLI 调用 Codex，也支持按需接入 OpenClaw Shell
- 在提交和推送前执行本地检查
- 自动创建 PR，并为每次运行保留审计记录
- 支持通过 webhook 继续处理 PR 反馈和 CI 故障恢复
- 支持 Azure DevOps 与 GitHub 的 provider-neutral 路由
- 支持离线 `local-task` 模式，可直接消费本地仓库、本地任务文件和本地 review 工件
- 支持导出可搬运部署包，并提供 `load-images` / `up-offline` 脚本用于无外网环境
- 内置 GitHub Actions 安装包工作流，可产出在线安装包，并按需附带离线镜像归档
- 提供 Windows、Linux systemd 和 Docker 部署资产

## 仓库结构

- `ado_client/`：Azure DevOps REST 客户端，负责工作项、仓库、PR 和构建操作
- `codex_acp_runner/`：ACP 执行器封装与结构化结果处理
- `github_client/`：GitHub REST 客户端，负责 issue、PR 评论与 checks 操作
- `harness_runtime/`：Bridge 服务、编排逻辑与运行时配置加载
- `local_client/`：本地离线任务 provider，负责本地仓库、本地任务文件与本地 review 工件流程
- `rocketchat_notifier/`：Rocket.Chat webhook 通知器
- `run_store/`：SQLite schema 与运行态持久化原语
- `skills/`：ClawHarness 的 canonical skill source 与 registry
- `workflow_provider/`：共享的 provider-neutral 事件与客户端契约
- `openclaw-plugin/`：OpenClaw 插件入口、hooks、flows，以及供 OpenClaw 消费的生成 skill 镜像
- `deploy/`：Docker、systemd、Windows 以及配置模板
- `.omx/plans/`：PRD、测试规范、PDCA 记录与验收证据

## 文档索引

- `docs/system-architecture.md`：V3 系统架构总览、运行时分层与部署拓扑
- `deploy/README.md`：部署方式、配置项与运维说明
- `docs/plugin-architecture.md`：plugin、skill、workflow 与 runtime 边界摘要
- `docs/plugin-boundary.md`：职责归属与维护边界规则
- `docs/plugin-skill-workflow-boundary.md`：skill / workflow / capability 详细边界说明
- `skills/README.md`：canonical skill 归属与投影说明
- `.omx/plans/prd-clawharness-v3-2026-04-09.md`：V3 本地优先 / 插件化 / 轻量化产品定义
- `.omx/plans/test-spec-clawharness-v3-2026-04-09.md`：V3 验收标准与验证门槛
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`：V2 产品定义与范围
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`：V2 验收标准与测试门槛
- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`：最新 V2 真实验收证据
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`：V1 真实验收历史与 PDCA 记录

## 当前状态

- 最新本地验证结果：
  `python -m unittest discover -s tests -v` -> `175/175` 通过
- 最新结构化验证结果：
  `python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests deploy/package deploy/windows` -> 通过
- V3 的本地优先 / 插件化 / 可选 Shell 基线已经完成，并通过 architect 复核
- Azure DevOps 的 task -> branch -> PR 真实闭环已经跑通
- 同父 run 的 PR feedback 恢复已经真实跑通
- 同父 run 的 CI recovery 已完成真实端到端闭环：
  work item `45` -> run `manual-ai-review-test-45` -> PR `27` -> 失败 build `42` -> 子 run `manual-ai-review-test-45--ci-recovery--f7ccbe33` -> 成功重试 build `43`
- PR merge 收口现在也已经完成真实验证：
  合并事件会统一归一化成 `pr.merged`，根 run 自动置为 `completed`，并在 provider 支持时自动回写任务完成状态
- Azure hello-world 的最终闭环现在已完成端到端验证：
  work item `46` -> run `manual-ai-review-test-46` -> PR `28` -> build `44` -> PR merged -> run completed -> Azure work item completed
- 本地 Docker 栈已完成真实验证：
  `openclaw-gateway`、`clawharness-bridge`、`openclaw-bot-view`
- 离线 Docker 的 `local-task` 主链路现已完成真实端到端验证：
  task file `task-002` -> run `manual-local-repo-task-002` -> branch `refs/heads/ai/task-002-add-offline-validation-note` -> 本地 commit `4cca6c1` -> 本地 review 工件 `local-0eedc568`
- 默认离线安全策略也已完成真实验证：
  当 `LOCAL_PUSH_ENABLED=0` 时，源仓库保持不变，只有隔离 workspace 会生成分支和提交
- `bot-view` 控制面已经在 Docker 栈上完成真实验证：
  `/clawharness` 读接口、`Pause`、`Resume`、`Add Context` 以及审计链更新都已经对真实 run 跑通
- Windows self-hosted Azure agent 的 PowerShell 环境问题已完成真实排障和修复，修复方式已写入 `deploy/README.md`
- GitHub provider 现在已经完成 live webhook 入口验证：通过 `smee.io` 把真实 GitHub issue 事件转发到本机临时 bridge，并成功创建 GitHub-backed run、准备 Windows 工作区
- GitHub 在 Windows 上的 issue -> PR stdin 重跑链路已经完成真实验证：
  issue `#7` -> run `34a87604-6c44-4177-86b1-7676cb77f6cf` -> PR `8`
- GitHub 的 PR feedback 与 checks recovery 仍然是“能力已实现，但还需要在真实 webhook 仓库里补更广泛验收”的状态

## 当前推荐用法

- 默认优先使用 Docker 的 core-only 栈
- 默认保持 `HARNESS_PROVIDER_PROFILE=local-task`
- 只有在需要 OpenClaw UI、聊天宿主或 bot-view 时才开启 `--profile shell`
- 如果还需要 dashboard sidecar，则开启 `--profile shell --profile bot-view`
- 如果你要启用可交互的 bot-view 控制面，请设置 `HARNESS_CONTROL_TOKEN`；如果要把只读和控制分权，再额外设置 `HARNESS_API_TOKEN` 或 `HARNESS_READONLY_TOKEN`
- 远端 provider 里，Azure DevOps 仍是当前最完整的真实验收路径

## 当前交付能力

- bridge 现在已经提供只读运行态 API，可查询 run 汇总、run 列表、run 详情、审计时间线和 run graph
- bridge 现在还提供了受控的 `POST /api/runs/<run_id>/command`，可审计地执行 `pause`、`resume`、`add-context`、`escalate`
- PR merge 事件现在会通过 provider-neutral 的 `pr.merged` 自动把根 run 收口为 `completed`
- 根 run 完成后，bridge 现在会自动尝试回写 provider 侧任务状态；Azure DevOps 与 GitHub 都已接入这条路径
- 如果任务回写失败，run 仍保持 `completed`，同时把失败原因记为 `task_completion_sync_failed` 审计事件，不回滚主闭环
- PR 反馈与 CI 故障恢复现在会在同一父 run 下创建恢复子 run，并记录 checkpoint 与 artifact
- PR 反馈与 CI 故障恢复现在按“父 run + 恢复类型”做 single-flight 保护，并把 follow-up 锁预算至少覆盖 executor timeout 且额外预留 300 秒缓冲，避免同一分支/工作区上并发恢复互相踩踏
- Rocket.Chat 入站命令现在已经支持 `status`、`detail`、`pause`、`resume`、`add-context`、`escalate`，并具备对话线程绑定与命令审计
- 新增了 Weixin 兼容命令入口 `POST /webhooks/chat/weixin`，沿用同一套命令语义
- 通过聊天追加的图片附件现在会自动走 OpenAI 兼容 `responses` 接口分析，并以 `image-analysis` 形式写回 run 证据链
- 运行时核心现在已经通过 provider adapter 处理 task、PR feedback 与 CI recovery，不再直接绑定 Azure 私有动作名
- GitHub issue、PR 评论与 checks failure 现在会进入与 Azure DevOps 相同的 run graph、状态机与恢复链路
- 运行时现在会按 run 类型与 agent 角色自动选择带版本号的 ClawHarness skill pack，并把选择结果写入 run 证据链，便于审计
- 运行时现在提供 retention 驱动的 maintenance 入口，可清理过期终态 workspace，同时不影响活跃 run 的恢复状态
- Docker 现在支持可选的 `bot-view` profile，用于启动 OpenClaw dashboard sidecar
- sidecar 中新增了 `/clawharness` 页面，可把 ClawHarness 的 run 与审计数据代理进 dashboard 观察面，并额外汇总闭环状态卡与人工干预态势，同时提供 `Pause`、`Resume`、`Escalate`、`Add Context` 控制区
- 运行时新增了 `local-task` provider，可在离线或实验环境中走“本地任务文件 -> 本地工作区 clone -> 本地分支 -> 本地提交 -> 本地 review 工件”闭环
- 部署包导出器现在会额外生成 `load-images` 与 `up-offline` 脚本，便于把 Docker 部署目录整体搬到离线机器直接启动
- executor 结果解析现在可以兼容模型返回的字符串型 `checks`，会自动归一化成 informational 项，而不会因为解析失败中断主链路

## 最快启动路径

在 Windows 上，最短路径是：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -OpenAiApiKey <your-key>
```

如果你更希望走简化后的交互式安装向导，可以直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -Interactive
```

现在在交互式 PowerShell 里直接运行 `deploy/windows/bootstrap.ps1`，也会自动进入快速向导。
向导在真正写入配置前会先展示安装摘要，结束后会自动执行一次安装检查。

如果你确实需要原生安装、更多目录项或完整高级参数，再使用：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/bootstrap.ps1 -Interactive -Advanced
```

这个统一安装器还支持：
`-InstallMode docker`、`-InstallMode native-core`、`-InstallMode native-openclaw`。
如果本机还没装 Docker Desktop，可追加 `-InstallDocker`。
如果你只想先生成 `.env`、数据目录和 token，而不立刻启动容器，可追加 `-SkipStart`。
如果你想顺手生成一个本地离线任务示例文件，可追加 `-CreateSampleTask`。
安装或配置完成后，可用下面的命令检查当前模式是否已经准备完整：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/windows/check-install.ps1 -InstallMode docker
```

如果你部署的是原生模式，把 `docker` 改成 `native-core` 或 `native-openclaw` 即可。
当前默认 Docker 打包方式仍是“单机单实例”，因为 compose 使用了固定容器名。

1. 把 `deploy/docker/.env.example` 复制成 `deploy/docker/.env`
2. 保持 `HARNESS_PROVIDER_PROFILE=local-task`
3. 至少填写这些变量：
   `OPENAI_API_KEY`、`LOCAL_REPO_PATH`、`LOCAL_TASKS_PATH`、`LOCAL_REVIEW_PATH`
4. 启动 core-only 服务栈：

```sh
docker compose --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

5. 如果还想叠加 OpenClaw Shell：

```sh
docker compose --profile shell --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

6. 如果还想要 dashboard sidecar，再执行：

```sh
docker compose --profile shell --profile bot-view --env-file deploy/docker/.env -f deploy/docker/compose.yml up --build -d
```

如果希望 dashboard 支持交互控制，请同时设置 `HARNESS_CONTROL_TOKEN`。
如果只想暴露只读 dashboard，可设置 `HARNESS_API_TOKEN` 或 `HARNESS_READONLY_TOKEN`。
当只配置了 `HARNESS_CONTROL_TOKEN` 时，sidecar 的只读代理现在也会自动回退使用它。

7. 具体运维和配置细节看 `deploy/README.md`

## 离线模式

如果目标环境不方便接 Azure DevOps 或 GitHub，ClawHarness 现在默认就是 `local-task` 本地闭环：

- 保持 `deploy/config/providers.yaml` 默认配置不变
- 配置 `LOCAL_REPO_PATH`、`LOCAL_TASKS_PATH`、`LOCAL_REVIEW_PATH`
- 用本地任务文件触发一次运行

示例：

```sh
python -m harness_runtime.main --provider-type local-task --task-id task-001
```

如果 `local-task.repository_path` 已配置，`--repo-id` 可以省略。
运行完成后会在 `.clawharness-review/` 或 `LOCAL_REVIEW_PATH` 下生成本地 review markdown 工件。

如果你要把 Docker 方案带到离线机器：

1. 导出独立部署包：

```sh
python deploy/package/export_deploy_bundle.py --output dist/clawharness-deploy --force
```

2. 在有网机器准备镜像并导出：

```sh
docker save -o clawharness-images.tar \
  clawharness/openclaw-gateway:local \
  clawharness/harness-bridge:local \
  clawharness/openclaw-bot-view:local
```

3. 将部署包和 `clawharness-images.tar` 一起复制到目标机器，先执行 `load-images`，再执行 `up-offline`。

如果目标机器是 Windows，也可以直接运行：

```powershell
./bootstrap.ps1 -OpenAiApiKey <your-key>
```

然后再执行：

```powershell
./check-install.ps1 -InstallMode docker
```

## GitHub Actions 安装包

仓库现在内置了 [`.github/workflows/package-installers.yml`](.github/workflows/package-installers.yml)，用于在 CI 中产出可下载安装包。

- 推送到 `main`，或推送匹配 `v*` 的 tag 时，会自动生成在线安装包 artifact。
- 推送匹配 `v*` 的 tag 时，还会自动构建离线 Docker 镜像归档，并把打包结果直接挂到该 tag 对应的 GitHub Release。
- 手动触发 `workflow_dispatch` 时，如果把 `include_offline_images` 设为 `true`，还会额外构建并附带离线 Docker 镜像归档。
- 打包结果会包含：
  `clawharness-deploy-<label>.zip`、
  `SHA256SUMS-<label>.txt`、
  `artifact-manifest-<label>.json`，
  如果启用了离线镜像，则还会包含 `clawharness-images-<label>.tar`。

如果你要在本地复现与 CI 相同的打包流程，可执行：

```sh
python deploy/package/package_release_assets.py --output dist/github-actions --label local --force
python deploy/package/package_release_assets.py --output dist/github-actions --label local --image-archive clawharness-images.tar --force
```

## 快速开始

1. 先配置任务 provider 所需环境变量。
   如果走本地优先，直接使用默认 `deploy/config/providers.yaml`。
   如果使用 Azure DevOps，可改用 `deploy/config/providers.azure-devops.yaml`，或把 `HARNESS_PROVIDER_PROFILE` 设为 `azure-devops`。
   如果使用 GitHub，可改用 `deploy/config/providers.github.yaml`，或把 `HARNESS_PROVIDER_PROFILE` 设为 `github`。
   只有启用 shell 的部署才需要填写 `OPENCLAW_HOOKS_TOKEN` 与 `OPENCLAW_GATEWAY_TOKEN`。
2. 阅读 `deploy/README.md` 选择部署方式。
3. 按目标环境运行 Windows 安装脚本，或者使用 Docker / systemd 资产。
4. 运行自动化检查：

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
```

5. 手工触发一次任务运行：

```sh
python -m harness_runtime.main --provider-type local-task --task-id <task-id>
```

## 验证范围

当前实现已经在 Azure 主链路上完成真实验证：

- 任务认领与去重
- 执行阶段
- 本地检查门禁
- 分支推送
- PR 创建
- PR 合并后自动收口 run
- run 完成后自动回写 provider 侧任务状态
- PR 反馈与 CI 恢复后的同父 run 子链路续跑，并保留子 run 证据

当前仍需要补齐更广泛真实环境验证的部分主要是：

- 真实 GitHub PR feedback 与 checks recovery 链路的 live webhook 验证
- 受保护分支和评审策略更严格的仓库策略联动
- Linux 原生和非本机环境部署的更广覆盖验证
