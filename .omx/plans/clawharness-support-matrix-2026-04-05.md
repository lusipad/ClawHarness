# ClawHarness 支持矩阵与 Provider 配置说明

已被替代：`.omx/plans/clawharness-master-plan-2026-04-05.md`

日期：2026-04-05
状态：归档中的支持矩阵基线，已补 2026-04-06 状态快照
依赖：
- `.omx/plans/clawharness-architecture-2026-04-05.md`
- `.omx/plans/clawharness-mvp-technical-design-2026-04-05.md`

## 归档状态更新

截至 `2026-04-06` 的实际支持状态：

- 任务 / PR / CI provider
  - Azure DevOps：已实现，已真实验证
  - GitHub：已实现，已通过本地测试，live 联调阻塞于 `GITHUB_TOKEN`
- 聊天 provider
  - Rocket.Chat webhook / command：已实现
  - Weixin：仍处于规划项
- 编码执行器
  - OpenClaw 路径：已实现
  - 本地 Codex CLI backend：已实现
- 打包形态
  - Docker：已真实验证
  - Windows 原生：本机安装与运行已验证
  - Linux systemd：部署资产已提供，但更广泛真实覆盖仍待补

## 用途

定义 Harness 如何支持：

- Azure DevOps Services 与 Azure DevOps Server
- Docker 与非 Docker 部署
- 多种聊天集成模式
- 多种编码执行器

核心规则：

**一套工作流模型，多种 provider 模式**

也就是说：

- OpenClaw flows 和 skills 不应按供应商分叉
- 真正变化的部分只应在 provider adapter 层

## 支持维度

平台存在四个可替换接缝：

1. 任务 / PR / CI provider
2. 聊天 provider
3. 编码执行器
4. 运行时打包形态

## 归档结论

这份支持矩阵的关键结论已经吸收到主计划与 PRD 中：

- V1 基线采用 `ado-rest` + `rocketchat-webhook` + `codex-acp`
- 运行时存储固定为 SQLite
- Docker 与原生安装都必须保留
- 共享 flow 必须保持统一能力名，不允许直接写死供应商调用

如果后续需要扩展更多 provider 模式，应在不破坏统一 flow 契约的前提下新增 adapter，而不是复制一套新的工作流。
