# ClawHarness 总体主计划

日期：2026-04-05
状态：统一主计划，已补 2026-04-06 实现状态
替代：
- `.omx/plans/clawharness-architecture-2026-04-05.md`
- `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md`
- `.omx/plans/clawharness-support-matrix-2026-04-05.md`

## 2026-04-06 状态快照

已真实验证：

- Azure DevOps task -> branch -> PR
- 同父 run 的 PR feedback 恢复
- 同父 run 的 CI recovery 自动修复与自动重试
- Docker 栈：
  - `openclaw-gateway`
  - `clawharness-bridge`
  - `openclaw-bot-view`

已实现并通过本地验证：

- provider-neutral runtime
- GitHub adapter 与 checks / review 恢复路径
- Rocket.Chat 命令入口
- 图片分析工件链路
- skill registry
- maintenance 清理入口

仍未完成真实外部联调：

- GitHub live webhook 闭环
  - 当前原因：`GITHUB_TOKEN` 未配置
- Linux systemd 的更广泛真实部署覆盖

## 目标

构建一个内部 AI 软件交付 Harness，满足以下闭环：

- 从 Azure DevOps 接收工作项
- 由 OpenClaw 完成分析与规划
- 通过 ACP 调用 Codex 实施代码修改
- 自动创建分支与 PR
- 对 PR 评论与 CI 失败做后续恢复
- 向 Rocket.Chat 发送状态通知
- 支持 Docker 和非 Docker 原生部署

## V1 固定决策

以下决策在 V1 阶段视为锁定，除非后续 ADR 显式替代：

- `OpenClaw` 是控制中心
- `Codex` 通过现成的 `ACP` 集成，不引入自定义执行协议
- Azure DevOps 集成先从 `REST` 起步，不把 MCP 作为前置
- Rocket.Chat 先采用 `webhook 通知模式`，不引入完整聊天桥接
- 运行时存储只使用 `SQLite`
- V1 只需要一个 `OpenClaw Gateway`
- 每个任务运行创建一个独立工作区
- V1 不做自动合并
- V1 不做多供应商运行时
- V1 不引入笨重的外部编排器

## 不做的内容

- 新的通用 Agent 平台
- 完整的供应商市场
- 脱离 OpenClaw 的复杂工作流引擎
- 第二套聊天抽象层
- 超出 ACP 既有能力的第二套执行器抽象
- Azure DevOps Services 与 Azure DevOps Server 的双分支流程体系

## 最终形态

```text
Azure DevOps
  -> webhook 或 polling
  -> OpenClaw hook / bridge
  -> task-run flow
  -> OpenClaw planning
  -> Codex via ACP
  -> git push + PR
  -> Rocket.Chat webhook 通知
```

如果当前安装的 OpenClaw hook 面足够，就全部放在插件包内完成。
如果不足，则只补一个很小的 companion process，用于：

- 接收 webhook
- 写入 SQLite
- 唤醒 OpenClaw

这个 companion process 不是完整编排器。

## 核心组件

### 1. OpenClaw

OpenClaw 负责：

- 会话
- 规划
- flows
- hooks
- 任务续跑
- 通过 ACP 分发执行

### 2. run_store

运行时状态中心，负责：

- 任务认领
- 去重
- 锁
- 运行状态迁移
- run 映射
- 审计链路

### 3. ado_client

Azure DevOps 适配层，负责：

- 工作项读取与更新
- 仓库信息与工作区准备
- 分支创建
- 提交与推送
- PR 创建、查询、评论读取与回复
- Build 查询与重试
- 事件归一化

### 4. codex_acp_runner

ACP 执行封装层，负责：

- 把任务转成 ACP 请求
- 接收结构化执行结果
- 为任务主链路和恢复链路提供统一执行契约

### 5. rocketchat_notifier

通知层，负责：

- 任务开始
- PR 创建
- CI 失败
- 任务阻塞
- 任务完成

## 核心流程

### task-run

1. 接收 Azure DevOps 任务事件
2. 归一化事件并尝试认领
3. 准备仓库工作区
4. 创建任务分支
5. 调用 ACP 执行任务
6. 执行本地检查
7. 提交、推送并创建 PR
8. 记录审计并发送通知

### pr-feedback

1. 由 `pr_id` 找回同一 `run_id`
2. 拉取未解决评审评论
3. 在同一工作区和分支上下文中继续修复
4. 执行本地检查
5. 更新分支并回帖
6. 将运行状态恢复到 `awaiting_review`

### ci-recovery

1. 由 `ci_run_id` 找回同一 `run_id`
2. 读取失败构建摘要
3. 判断是可自动恢复还是应升级人工
4. 可恢复时修补、检查、推送并重试
5. 不可恢复时转 `awaiting_human`

## 运行状态

- `queued`
- `claimed`
- `planning`
- `coding`
- `opening_pr`
- `awaiting_ci`
- `awaiting_review`
- `awaiting_human`
- `completed`
- `failed`
- `cancelled`

## V1 验收闭环

V1 以以下验收点为准：

- AC-01 单任务认领与去重
- AC-02 结构化规划输出
- AC-03 ACP 编码执行
- AC-04 PR 前检查门禁
- AC-05 分支推送与 PR 创建
- AC-06 PR 反馈恢复
- AC-07 CI 失败恢复
- AC-08 Rocket.Chat 生命周期通知
- AC-09 Docker 部署支持
- AC-10 原生部署支持
- AC-11 工作流稳定性规则
- AC-12 安全与策略护栏
- AC-13 可观测性与审计

## 实施顺序

1. 运行时存储与状态机
2. Azure DevOps Provider 基线
3. ACP 执行契约
4. 主 task-run 流程
5. PR/CI 恢复流程
6. 通知与部署
7. 审计、策略与收口

## 当前结论

截至 `2026-04-06`：

- 任务到分支到 PR 主链路已真实验证
- PR 反馈恢复链路已真实验证
- CI 恢复链路已完成真实 live 闭环
- Docker + bot-view sidecar 已真实验证
- GitHub adapter 已实现并通过本地测试，但 GitHub live 仍受 `GITHUB_TOKEN` 阻塞
- Linux / 更严格受保护分支策略等更强环境约束仍需继续验证
