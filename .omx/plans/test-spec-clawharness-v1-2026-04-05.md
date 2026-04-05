# ClawHarness v1 验收测试规范

日期：2026-04-05
状态：验收基线
配套文档：
- `.omx/plans/prd-clawharness-v1-2026-04-05.md`
- `.omx/plans/clawharness-master-plan-2026-04-05.md`

## 基线来源

- MVP 验收项与构建顺序来自总体主计划
- Provider 兼容性、工作流稳定性规则和部署验证来自 support matrix
- TaskFlow、skill、执行器、部署、安全与监控要求来自 MVP 技术设计

## 验收原则

- 每条验收标准都必须能由可观察证据证明
- 共享 flow 只有在保持供应商中立并依赖统一能力名时才算通过
- 恢复行为只有在复用同一运行上下文时才算通过
- Docker 与原生支持都属于 P0，不能在 MVP 收口前被移出
- `ado-mcp`、`rocketchat-bridge` 等 P1 特性不能成为 MVP 验收前提

## 测试层级

### 第 1 层：静态与工件验证

用途：
- 验证必需文件、schema、配置模板和 flow 引用存在且自洽

证据：
- schema 文件
- provider 与 policy 模板
- flow 与 skill 定义
- 部署资产

### 第 2 层：组件验证

用途：
- 在端到端执行前，先单独验证各模块

证据：
- run-store 的去重、锁和状态迁移测试
- Azure DevOps 适配器测试
- ACP 执行器运行与恢复测试
- Rocket.Chat 通知器测试

### 第 3 层：流程集成验证

用途：
- 验证主运行闭环

证据：
- `task-run` happy path
- `pr-feedback` 恢复路径
- `ci-recovery` 自动修复或升级路径

### 第 4 层：运维验证

用途：
- 验证部署、策略和可运维边界

证据：
- Docker 重启持久性
- 原生服务重启行为
- 健康检查
- 审计事件
- 密钥处理

## 验收标准

### AC-01：单任务认领与去重

要求：
- 一个合格 Azure DevOps 任务只创建一个活动 run

给定：
- 一条合格任务事件
- 同一事件的一次或多次重复投递

当：
- 入站路径归一化并处理事件

则：
- 只创建一个 `TaskRun`
- 锁只被一个 owner 持有
- 重复投递被记录为去重事件，而不是新 run

证据：
- runtime store 中的 run 记录
- replay 事件的 dedupe 记录
- 显示“一个认领成功、重复被拒绝”的审计或日志

### AC-02：结构化规划输出

要求：
- 在编码前先产出结构化计划

给定：
- 归一化任务载荷
- 仓库上下文

当：
- `analyze-task` 执行

则：
- 输出包含计划摘要
- 明确列出受影响文件或模块
- 明确暴露缺失信息与风险等级

证据：
- 保存的 `analyze-task` 工件
- 显示进入 `planning` 状态的 flow 记录

### AC-03：Codex ACP 编码执行

要求：
- OpenClaw 能通过 ACP 调起 Codex 并收到结构化执行结果

给定：
- 已准备好的工作区
- 结构化计划或等价任务提示

当：
- 编码执行被触发

则：
- ACP 请求被成功发出
- 执行结果包含 `status`、`summary`、`changed_files`、`checks`、`follow_up`

证据：
- ACP 请求记录
- 执行结果工件

### AC-04：PR 前检查门禁

要求：
- 在推送和开 PR 之前必须先跑本地检查

给定：
- 已完成的代码修改

当：
- flow 尝试发布分支

则：
- 先执行检查
- 只有检查通过才允许进入发布
- 检查失败时 run 转入阻塞或人工处理状态

证据：
- `checks_completed` 审计记录
- 检查命令输出

### AC-05：分支推送与 PR 创建

要求：
- 主流程必须能从任务分支走到 PR 创建

给定：
- 已通过检查的工作区修改

当：
- `task-run` 完成发布

则：
- 产生任务分支
- 成功推送远端
- 成功创建 PR
- run 进入 `awaiting_review` 或 `awaiting_ci`

证据：
- run 记录中的 branch 和 PR id
- push 与 create PR 的适配器输出

### AC-06：PR 反馈恢复

要求：
- PR 评论到来时，必须恢复到同一 run

给定：
- 已有关联 `pr_id` 的 run
- 一条新的 PR 评论事件

当：
- `pr-feedback` 处理事件

则：
- 系统能解析 `pr_id -> run_id`
- 使用同一 run 上下文继续处理
- 处理未解决评论
- 不创建第二个 run

证据：
- PR 到 run 的映射记录
- `pr-feedback` 审计链
- 未变化的 `run_id`

### AC-07：CI 失败恢复

要求：
- CI 失败事件必须回到同一 run，并走“修补重试”或“升级人工”之一

给定：
- 已有关联 `ci_run_id` 的 run
- 一条失败 CI 事件

当：
- `ci-recovery` 处理事件

则：
- 系统能解析 `ci_run_id -> run_id`
- 恢复到同一 run
- 最终结果是“修补并重试”或转入 `awaiting_human`

证据：
- CI 到 run 的映射记录
- 恢复决策记录
- 重试输出或升级审计

### AC-08：Rocket.Chat 生命周期通知

要求：
- 生命周期事件应能送达 Rocket.Chat

给定：
- 已配置 webhook
- started、PR opened、CI failed、blocked、completed 等事件

当：
- 通知被触发

则：
- 消息格式正确
- 发送成功时可见
- 发送失败不打断主业务路径

证据：
- notifier 测试
- webhook 调用记录
- 失败场景审计

### AC-09：Docker 部署支持

要求：
- 项目必须可通过 Docker 启动

给定：
- Docker 可用
- 配置和密钥齐备

当：
- 启动 compose 栈

则：
- gateway 和 bridge 能启动
- 基本健康检查通过

证据：
- compose 资产
- 健康检查输出

### AC-10：原生部署支持

要求：
- 项目必须支持原生安装方式

给定：
- Windows 或 Linux 原生环境

当：
- 按部署脚本安装并启动

则：
- gateway / bridge 能在原生环境运行
- 可重新启动并恢复配置

证据：
- systemd / Windows 资产
- 原生环境验证记录

### AC-11：工作流稳定性规则

要求：
- flow 必须依赖统一能力名，而不是供应商特定调用

给定：
- 插件 flow 定义

当：
- 审查 flow 契约

则：
- 共享 flow 不直接依赖 `ado.*`、`rocketchat.*`、`codex.*` 之类供应商专用动作名

证据：
- 静态检查结果
- flow 定义

### AC-12：安全与策略护栏

要求：
- V1 必须具备最小可执行的策略护栏

给定：
- 部署配置
- 仓库策略约束

当：
- 运行主链路或恢复链路

则：
- 不允许绕过受保护分支规则
- 不允许直接合并
- 密钥通过环境变量或等价安全方式注入

证据：
- policy 配置
- 部署环境变量验证
- 策略相关实现说明

### AC-13：可观测性与审计

要求：
- 关键运行节点必须留下可追踪证据

给定：
- 一次完整运行或恢复链路

当：
- flow 执行

则：
- run、状态迁移、检查、发布、阻塞等关键事件有审计记录
- 健康检查和基本运维入口存在

证据：
- SQLite 审计库
- 审计链条
- 健康检查脚本

## 当前 live 结论

截至 `2026-04-05`：

- AC-01 至 AC-06 已有本地或真实环境证据
- AC-06 已完成真实环境闭环
- AC-07 实现完成并本地验证通过，但 live 验证被目标项目缺少 CI builds 阻塞
- AC-09 至 AC-13 仍需按环境继续逐项收口
