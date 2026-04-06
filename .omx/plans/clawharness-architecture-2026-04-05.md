# ClawHarness 架构说明

已被替代：`.omx/plans/clawharness-master-plan-2026-04-05.md`

日期：2026-04-05
状态：归档中的架构基线，已补 2026-04-06 状态指针
范围：面向内网部署的 AI 软件交付 Harness，支持可插拔的 DevOps、聊天与编码执行器

## 归档状态更新

截至 `2026-04-06`，这份架构稿里的核心判断已经在当前仓库中落地，并补齐了新的真实验证结果：

- Azure DevOps task -> PR 已真实跑通
- 同父 run 的 PR feedback 恢复已真实跑通
- 同父 run 的 CI recovery 已真实跑通
- Docker + bot-view sidecar 已在本机真实跑通
- GitHub adapter 已实现并通过本地测试，但真实 webhook 联调仍受 `GITHUB_TOKEN` 未配置阻塞

当前应优先参考：

- `.omx/plans/clawharness-master-plan-2026-04-05.md`
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`
- `.omx/plans/evidence-clawharness-v2-2026-04-06.md`

## 架构目标

构建一个内部 AI 软件交付系统，能够：

- 从 Azure DevOps 等任务系统接收工作
- 让 AI 代理完成分析与规划
- 通过可切换的编码执行器完成代码修改
- 通过可切换聊天渠道发送状态反馈
- 打开 PR，并对评审与 CI 反馈继续迭代
- 同时支持 Docker 与非 Docker 部署
- 在未来保留更换 DevOps、聊天和编码后端的可能

## 非目标

- 从零构建一个通用 Agent 平台
- 取代 DevOps、Git、PR 或 CI 系统作为源事实系统
- 第一版就完成完整企业级 IAM / SSO 统一
- 构建多租户 SaaS 架构

## 架构原则

1. OpenClaw 是 AI 控制平面。
2. 供应商专有 API 应留在插件、MCP 工具或适配器后面。
3. 可靠性逻辑要薄且显式，不应藏在 prompt 中。
4. Skill 应暴露稳定的业务能力，而不是供应商品牌命令。
5. 部署包必须同时支持 Docker 与原生服务安装。
6. 更换供应商时，系统应尽量优雅降级。

## 归档结论

这份架构稿的关键判断已经合并进主计划：

- OpenClaw 作为中心
- provider-neutral 的 flow 契约
- 薄 bridge / runtime，而不是重型外部编排器
- Docker 与原生安装并行支持

如需继续设计，以总体主计划和 PRD 为准，不再以本文件为新的实现依据。
