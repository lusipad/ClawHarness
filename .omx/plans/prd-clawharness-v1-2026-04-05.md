# ClawHarness v1 PRD 与交付计划

日期：2026-04-05
状态：执行基线
展开自：
- `.omx/plans/clawharness-master-plan-2026-04-05.md`
- `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md`
- `.omx/plans/clawharness-support-matrix-2026-04-05.md`

## 基线来源

- 产品目标、固定决策、模块边界和主流程来自总体主计划
- 支持矩阵、工作流稳定性规则和部署验证来自 support matrix
- TaskFlow、skill 契约、执行器契约、部署布局和安全策略来自 MVP 技术设计

## 产品目标

构建一个尽可能小、但能真实落地的内部 AI 软件交付 Harness：

- 从 Azure DevOps 接收工作
- 由 OpenClaw 分析与规划
- 通过 ACP 调用 Codex 修改代码
- 自动开 PR
- 对 PR 评论和 CI 故障作出反应
- 发送 Rocket.Chat 生命周期通知
- 既支持 Docker 也支持原生安装

## V1 固定边界

- OpenClaw 是控制中心
- Codex 只通过 ACP 调度
- Azure DevOps 先使用 `ado-rest`
- Rocket.Chat 先使用 `rocketchat-webhook`
- SQLite 是唯一运行时存储
- 单 gateway、单 run 单 workspace
- 不做 auto-merge
- 不做多提供方扩展

## 规划假设

为了避免开放问题阻塞交付，本计划采用最低风险基线：

- Provider 组合：`ado-rest` + `rocketchat-webhook` + `codex-acp`
- 部署目标：同时保留 Docker 和原生部署能力，但优先验证最快能落地的路径
- Ingress 形态：优先使用插件原生 webhook；如果 OpenClaw 已安装 hook 面不足，则引入轻量 bridge，但不改变 flow 契约

## 范围

### 范围内

- `run_store`：SQLite schema、锁、去重、审计、run 映射
- `ado_client`：工作项、仓库、PR、CI 的 `ado-rest` 操作
- `codex_acp_runner`：主链路与恢复链路的 ACP 执行
- `rocketchat_notifier`：webhook 通知
- `openclaw-plugin`：flows、hooks、skills 和运行时组合
- `task-run`、`pr-feedback`、`ci-recovery`
- Docker 和原生安装的部署资产
- 验证脚本、运行手册、验收证据

### 范围外

- `ado-mcp` 作为必须运行路径
- `rocketchat-bridge` 作为 MVP 依赖
- 其他 ACP 执行器
- PostgreSQL / 多 gateway 协调
- 自动合并、通用 provider 市场、复杂审批 UI

## 成功指标

- 一个合格的 Azure DevOps 任务只创建一个活动 `TaskRun`
- 重复事件不会产生重复 run
- 同一时刻只有一个 owner 可以持有任务锁
- `task-run` 可以通过 ACP 走到分支推送和 PR 创建
- PR 评论与 CI 故障事件能回到同一运行上下文
- Rocket.Chat 能收到关键生命周期通知
- 同一套插件与配置模型能跑在 Docker 和原生部署下

## 工作流拆解

### 1. 运行时与持久化

目标：
- 定义可承载长会话和重复事件的运行时骨架

交付物：
- `run_store/schema.sql`
- 锁与去重规则
- run / audit 持久化 API
- 状态迁移规则

### 2. Azure DevOps Provider

目标：
- 实现 MVP 所依赖的具体 Provider 路径

交付物：
- `ado_client` 请求清单
- 任务、仓库、PR、CI 操作
- 事件归一化契约

### 3. 编码执行器

目标：
- 通过 ACP 把 OpenClaw 与 Codex 连接起来

交付物：
- `codex_acp_runner`
- 执行输入输出 schema
- 运行与恢复契约

### 4. OpenClaw 插件与流程编排

目标：
- 把运行时、provider 和执行器组成可恢复 flows

交付物：
- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`
- hooks 与 skills

### 5. 通知与部署

目标：
- 补齐可运行、可通知、可部署的最小操作面

交付物：
- `rocketchat_notifier`
- Docker 资产
- Windows / systemd 资产
- healthcheck 与验证脚本

## 关键需求

### 任务主链路

- 接到任务后必须完成去重与认领
- 运行前必须准备独立工作区
- 必须先检查、后发布
- PR 由 harness 创建，而不是执行器直接创建

### PR 恢复链路

- 必须通过 `pr_id -> run_id` 找回同一运行
- 必须使用同一 `workspace_path` 与 `branch_name`
- 必须处理未解决的评论
- 不允许为同一条反馈创建第二个 run

### CI 恢复链路

- 必须通过 `ci_run_id -> run_id` 找回同一运行
- 必须给出“自动恢复”或“升级人工”的清晰分流
- 恢复时必须保留审计证据

### 通知

- 至少覆盖 started、PR opened、CI failed、blocked、completed
- 通知失败不能打断主业务链路

### 部署

- 支持 Docker
- 支持 Windows 原生
- 支持 Linux systemd

## 验收入口

V1 是否关闭，以 `.omx/plans/test-spec-clawharness-v1-2026-04-05.md` 的 AC-01 至 AC-13 为准。
所有声称完成的能力都必须有对应证据记录在 `.omx/plans/evidence-clawharness-v1-2026-04-05.md`。

## 当前状态

截至 `2026-04-05`：

- 任务主链路已完成真实验证
- PR 反馈恢复已完成真实验证
- CI 恢复已实现并通过本地测试，但 live 验证受目标项目缺少构建资源阻塞
- 其余部署和策略能力已具备资产，但仍需按目标环境逐项验证
