# ClawHarness

[English](README.md) | 简体中文

ClawHarness 是一个面向 Azure DevOps 与 GitHub 仓库的自主化任务到 PR 执行闭环。它把 provider 侧任务来源、OpenClaw 执行、仓库本地校验、分支与 PR 自动化，以及可选的 Rocket.Chat 生命周期通知串成一条可重复的交付链路。

## 功能概览

- 使用基于 SQLite 的运行时存储完成任务认领、去重、加锁和审计
- 为每次任务运行准备隔离工作区，并创建任务分支
- 通过 OpenClaw 或本地 Codex CLI 后端调用 Codex 完成实现工作
- 在提交和推送前执行本地检查
- 自动创建 PR，并为每次运行保留审计记录
- 支持通过 webhook 继续处理 PR 反馈和 CI 故障恢复
- 支持 Azure DevOps 与 GitHub 的 provider-neutral 路由
- 提供 Windows、Linux systemd 和 Docker 部署资产

## 仓库结构

- `ado_client/`：Azure DevOps REST 客户端，负责工作项、仓库、PR 和构建操作
- `codex_acp_runner/`：ACP 执行器封装与结构化结果处理
- `github_client/`：GitHub REST 客户端，负责 issue、PR 评论与 checks 操作
- `harness_runtime/`：Bridge 服务、编排逻辑与运行时配置加载
- `rocketchat_notifier/`：Rocket.Chat webhook 通知器
- `run_store/`：SQLite schema 与运行态持久化原语
- `workflow_provider/`：共享的 provider-neutral 事件与客户端契约
- `openclaw-plugin/`：OpenClaw 插件入口、hooks、flows 与 skills
- `deploy/`：Docker、systemd、Windows 以及配置模板
- `.omx/plans/`：PRD、测试规范、PDCA 记录与验收证据

## 文档索引

- `deploy/README.md`：部署方式、配置项与运维说明
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`：V2 产品定义与范围
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`：V2 验收标准与测试门槛
- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`：最新 V2 真实验收证据
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`：V1 真实验收历史与 PDCA 记录

## 当前状态

- Azure DevOps 的 task -> branch -> PR 真实闭环已经跑通
- 同父 run 的 PR feedback 恢复已经真实跑通
- 同父 run 的 CI recovery 已完成真实端到端闭环：
  work item `45` -> run `manual-ai-review-test-45` -> PR `27` -> 失败 build `42` -> 子 run `manual-ai-review-test-45--ci-recovery--f7ccbe33` -> 成功重试 build `43`
- 本地 Docker 栈已完成真实验证：
  `openclaw-gateway`、`clawharness-bridge`、`openclaw-bot-view`
- Windows self-hosted Azure agent 的 PowerShell 环境问题已完成真实排障和修复，修复方式已写入 `deploy/README.md`
- GitHub provider 的代码与本地测试已就绪，但真实 GitHub webhook 联调仍受 `GITHUB_TOKEN` 未配置阻塞

## 当前 V2 交付能力

- bridge 现在已经提供只读运行态 API，可查询 run 汇总、run 列表、run 详情、审计时间线和 run graph
- PR 反馈与 CI 故障恢复现在会在同一父 run 下创建恢复子 run，并记录 checkpoint 与 artifact
- PR 反馈与 CI 故障恢复现在按“父 run + 恢复类型”做 single-flight 保护，并把 follow-up 锁预算至少覆盖 executor timeout 且额外预留 300 秒缓冲，避免同一分支/工作区上并发恢复互相踩踏
- Rocket.Chat 入站命令现在已经支持 `status`、`detail`、`pause`、`resume`、`add-context`、`escalate`，并具备对话线程绑定与命令审计
- 通过聊天追加的图片附件现在会自动走 OpenAI 兼容 `responses` 接口分析，并以 `image-analysis` 形式写回 run 证据链
- 运行时核心现在已经通过 provider adapter 处理 task、PR feedback 与 CI recovery，不再直接绑定 Azure 私有动作名
- GitHub issue、PR 评论与 checks failure 现在会进入与 Azure DevOps 相同的 run graph、状态机与恢复链路
- 运行时现在会按 run 类型与 agent 角色自动选择带版本号的 ClawHarness skill pack，并把选择结果写入 run 证据链，便于审计
- 运行时现在提供 retention 驱动的 maintenance 入口，可清理过期终态 workspace，同时不影响活跃 run 的恢复状态
- Docker 现在支持可选的 `bot-view` profile，用于启动 OpenClaw dashboard sidecar
- sidecar 中新增了 `/clawharness` 页面，可把 ClawHarness 的 run 与审计数据代理进 dashboard 观察面

## 快速开始

1. 先配置任务 provider 所需环境变量。
   如果使用 Azure DevOps，填写 `ADO_BASE_URL`、`ADO_PROJECT`、`ADO_PAT`。
   如果使用 GitHub，把 `deploy/config/providers.yaml` 切到 GitHub 配置，并填写 `GITHUB_TOKEN`。
   两种模式都需要填写 `OPENCLAW_HOOKS_TOKEN` 与 `OPENCLAW_GATEWAY_TOKEN`。
2. 阅读 `deploy/README.md` 选择部署方式。
3. 按目标环境运行 Windows 安装脚本，或者使用 Docker / systemd 资产。
4. 运行自动化检查：

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner github_client harness_runtime rocketchat_notifier run_store workflow_provider tests
```

5. 手工触发一次任务运行：

```sh
python -m harness_runtime.main --task-id <task-id> --repo-id <repo-id> [--provider-type github]
```

## 验证范围

当前实现已经在 Azure 主链路上完成真实验证：

- 任务认领与去重
- 执行阶段
- 本地检查门禁
- 分支推送
- PR 创建
- PR 反馈与 CI 恢复后的同父 run 子链路续跑，并保留子 run 证据

当前仍需要补齐更广泛真实环境验证的部分主要是：

- 真实 GitHub issue 到 PR、以及 checks 恢复链路的 live webhook 验证
- 受保护分支和评审策略更严格的仓库策略联动
- Linux 原生和非本机环境部署的更广覆盖验证
