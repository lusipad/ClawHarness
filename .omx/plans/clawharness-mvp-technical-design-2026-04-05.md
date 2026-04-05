# ClawHarness MVP 技术设计

已被替代：`.omx/plans/clawharness-master-plan-2026-04-05.md`

日期：2026-04-05
状态：归档中的 MVP 技术设计
依赖：`.omx/plans/clawharness-architecture-2026-04-05.md`

## 目标

定义一个尽可能小、但能跑通的实现，满足：

- 从 Azure DevOps 接收工作
- 让 OpenClaw 分析和规划
- 通过 ACP 把代码修改交给 Codex
- 创建分支与 PR
- 对 PR 评论和 CI 失败继续处理
- 发送 Rocket.Chat 通知
- 同时支持 Docker 与非 Docker 环境

## MVP 设计决策

首版把“重心”尽量留在 OpenClaw 内：

- 使用 OpenClaw Gateway
- 使用 OpenClaw TaskFlow
- 使用 OpenClaw hooks 与 webhooks
- 使用 OpenClaw skills
- 使用 OpenClaw ACP + Codex
- Azure DevOps 通过 MCP 或直接适配器接入

V1 不要求单独常驻的重型外部 orchestrator。

## Runtime 角色

如插件包本身不足以承载 webhook ingress 和运行时状态，可打包一个很小的 `harness runtime`，只负责：

- run registry
- dedupe
- task locks
- workspace / run / PR / CI 映射
- 审计记录
- 唤醒或继续正确的 flow

## 归档结论

这份技术设计中的主要实现判断已经进入当前实际代码：

- `run_store`
- `ado_client`
- `codex_acp_runner`
- `harness_runtime`
- `rocketchat_notifier`
- `openclaw-plugin`

后续实现与验证应以主计划、PRD、测试规范、证据和 PDCA 为准，不再继续扩展本归档稿。
