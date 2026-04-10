# ClawHarness 系统架构总览

日期：2026-04-09
状态：V3 已完成基线

## 架构结论

ClawHarness V3 的系统架构已经固定为三层：

1. `ClawHarness Core`
   负责任务闭环真相、provider-neutral 状态机、run graph、审计、checkpoint、artifact、能力装配。
2. `Codex Executor`
   负责真实编码执行、仓库修改、本地检查与结构化结果返回。
3. `OpenClaw Shell`
   负责可选的 Web UI、chat 宿主、bot-view、人工干预入口。

其中，V3 的关键变化是：

- 默认路径改为 `local-task + codex-cli + shell disabled`
- OpenClaw 不再是 core 的硬依赖，而是可选壳层
- provider / executor / notifier 全部进入统一 capability registry

## 设计目标

- 本地优先：默认在单机或隔离环境中即可跑通最小闭环
- 轻量部署：默认暴露稳定环境变量，而不是要求手工维护版本敏感配置
- 插件化扩展：把 provider、executor、notifier 这类差异收敛到 manifest + factory
- 长期工程化：保留 run graph、审计、恢复链路和可观测性，不退化成一次性脚本

## 组件视图

```text
                         +----------------------+
                         |  OpenClaw Shell      |
                         |  UI / Chat / BotView |
                         +----------+-----------+
                                    |
                                    | optional
                                    v
+------------------+      +----------------------+      +------------------+
| Task Provider    | ---> |  ClawHarness Core    | ---> | Codex Executor   |
| local / ADO / GH |      |  Bridge + Orchestr.  |      | codex-cli / ACP  |
+------------------+      +----------+-----------+      +------------------+
                                      |
                                      v
                             +-------------------+
                             | RunStore / Audit  |
                             | SQLite persistence|
                             +-------------------+
```

## 默认运行路径

V3 默认推荐路径是：

- `task-provider = local-task`
- `executor = codex-cli`
- `notifier = disabled or optional`
- `shell = disabled`

这条路径下：

- `harness_runtime.main` 会直接加载默认 `deploy/config/providers.yaml`
- runtime 不要求 `openclaw.json` 必须存在
- 手工任务可以直接通过 `python -m harness_runtime.main --provider-type local-task --task-id <task-id>` 触发
- Docker 也可以只启动 `harness-bridge`，不启动 `openclaw-gateway`

## 可选 Shell 叠加路径

当启用 `HARNESS_SHELL_ENABLED=1` 或 Docker `shell` profile 时：

- runtime 才会加载 `openclaw.json`
- `OpenClawWebhookClient` 才会被构造
- OpenClaw Shell 会承担 UI、chat 宿主、bot-view 叠加面
- Core 继续保留 run 生命周期真相，不把状态机让渡给 Shell

这意味着：

- Shell 可以缺席，但 Core 不能缺席
- UI/交互 可以替换，但 run / audit / recovery 不能分叉成第二套真相

## 核心模块分工

### 1. 配置与启动

入口：

- `harness_runtime/main.py`
- `harness_runtime/config.py`

职责：

- 解析 providers / policy / openclaw 配置
- 判断 shell 是否启用
- 加载 capability registry
- 按 capability type 实例化 provider / executor / notifier
- 构造 `TaskRunOrchestrator`、`HarnessBridge` 和 HTTP server

### 2. Bridge 层

入口：

- `harness_runtime/bridge.py`
- `harness_runtime/server.py`

职责：

- 接收 Azure DevOps / GitHub webhook
- 接收 Rocket.Chat / Weixin / bot-view 命令
- 把外部事件归一化成 task / PR / CI 三类运行事件
- 为 run 建立审计链、对话绑定、人工干预记录

### 3. Orchestrator 层

入口：

- `harness_runtime/orchestrator.py`

职责：

- claim 手工任务或 webhook 任务
- 准备 workspace、分支、执行器上下文
- 调用 executor
- 推进 run 状态机
- 打开 PR、等待反馈、触发 CI 恢复、落子 run 关系

### 4. 持久化与审计

入口：

- `run_store/`

职责：

- 保存 run、audit、checkpoint、artifact、skill_selection
- 提供去重、加锁、父子 run 关系、恢复链路基础能力
- 为 bot-view 与 API 查询提供统一底座

## Capability Registry 架构

V3 的插件化不是“市场化插件系统”，而是运行时装配边界。

当前已纳入统一 registry 的类型：

- `task-provider`
- `executor`
- `notifier`

对应实现：

- 注册中心：`harness_runtime/capability_registry.py`
- provider factory：`harness_runtime/provider_factories.py`
- executor / notifier factory：`harness_runtime/runtime_factories.py`
- 内建 manifests：
  - `harness_runtime/capabilities/builtin-task-providers.json`
  - `harness_runtime/capabilities/builtin-executors.json`
  - `harness_runtime/capabilities/builtin-notifiers.json`

当前内建能力：

- task-provider：`local-task`、`azure-devops`、`github`
- executor：`codex-cli`、`codex-acp`
- notifier：`rocketchat-webhook`

## Skill / Workflow / Plugin 关系

这三者在 V3 中严格分层：

- `skills/core/` 是 skill 真源
- `openclaw-plugin/skills/` 是兼容投影
- `openclaw-plugin/flows/*.yaml` 只保留流程引用，不再保存第二份 skill 正文
- capability manifest 只声明“可装配能力”，不声明业务闭环真相

如果你要看边界细节，继续参考：

- `docs/plugin-boundary.md`
- `docs/plugin-architecture.md`
- `docs/plugin-skill-workflow-boundary.md`

## 主链路视图

### A. 默认本地闭环

```text
local task file
  -> bridge / manual trigger
  -> orchestrator claim run
  -> workspace clone
  -> branch create
  -> codex-cli execute
  -> local checks
  -> local commit
  -> local review artifact
  -> run awaiting_review / completed evidence
```

### B. Azure / GitHub 远端闭环

```text
provider webhook or manual task
  -> provider normalize_event
  -> run claim + audit
  -> orchestrator execute
  -> branch / push / PR
  -> PR feedback or CI failure
  -> child run recovery
  -> PR merged
  -> root run completed
  -> provider task completion sync
```

### C. 可选人工干预链

```text
Rocket.Chat / Weixin / BotView
  -> bridge.handle_chat_command()
  -> pause / resume / escalate / add-context
  -> audit + checkpoint + artifact
  -> root run / child run 状态联动
```

## 部署形态

### 1. Core-Only / Local-First

最小部署：

- 只启动 `harness-bridge`
- provider 使用 `local-task`
- executor 使用 `codex-cli`
- shell disabled

适合：

- 单机开发
- 离线实验
- 可复制模板部署

### 2. Shell-Enabled

叠加部署：

- 增加 `openclaw-gateway`
- 可再增加 `openclaw-bot-view`
- Core 仍由 `harness-bridge` 承担真相

适合：

- 需要 UI
- 需要 chat 宿主
- 需要 bot-view 可观测与干预

## 可观测性与控制面

Core 对外暴露的运行态接口包括：

- `GET /healthz`
- `GET /readyz`
- `GET /api/summary`
- `GET /api/runs`
- `GET /api/runs/<run_id>`
- `GET /api/runs/<run_id>/audit`
- `GET /api/runs/<run_id>/graph`
- `POST /api/runs/<run_id>/command`

其中：

- GET 接口主要用于查询与 dashboard
- POST 命令接口用于 `pause`、`resume`、`add-context`、`escalate`
- bot-view 和聊天命令都复用同一套核心控制语义

## 扩展规则

后续扩展必须遵守以下约束：

1. 新 provider / executor / notifier 优先走 capability registry
2. 不在 Shell 层复制 Core 的状态机真相
3. 不新增第二套 skill 真源
4. flow 继续只保存引用，不回退成长 prompt 真文仓库
5. 若新增 UI 或 channel，也应消费 Core API，而不是旁路读写运行态

## 当前架构判断

截至 2026-04-09，ClawHarness 已从 “Azure + OpenClaw 偏重型集成” 收敛为：

- 默认可本地闭环
- 远端 provider 可叠加
- Shell 可选
- 能力装配统一
- 运行态真相单一

这就是 V3 架构完成的核心定义。
