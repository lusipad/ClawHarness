# ClawHarness V2 PRD 与路线图

日期：2026-04-05
状态：规划基线
配套文档：
- `.omx/plans/prd-clawharness-v1-2026-04-05.md`
- `.omx/plans/test-spec-clawharness-v1-2026-04-05.md`
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`

## V1 基线

ClawHarness V1 已经完成以下真实能力闭环：

- Docker 部署可用
- Azure DevOps 工作项到分支到 PR 的真实闭环已跑通
- PR 反馈恢复链路已跑通
- `bridge` 容器内官方 `codex exec` 已验证可用
- 当前代码基线已经具备运行时、适配器、插件和部署四个基本面

当前能力主要落在以下目录：

- `run_store/`：单 run 的去重、加锁、状态迁移、审计
- `harness_runtime/`：任务主链路编排、bridge 服务、配置加载
- `ado_client/`：Azure DevOps REST 适配
- `codex_acp_runner/`：Codex / ACP 执行封装
- `openclaw-plugin/`：OpenClaw flows、hooks、skills、插件入口
- `rocketchat_notifier/`：Rocket.Chat 生命周期通知
- `deploy/`：Docker、Windows、systemd 与配置模板

V1 的价值已经得到证明，但它仍然是一个以单任务、单主链路、低交互、低可视化为核心的闭环。它适合“从工作项到 PR”的最小交付验证，还不足以承载真正复杂、长期、可恢复、可协作的工程任务。

## V2 产品定义

ClawHarness V2 = 面向复杂工程任务的、可观察的、多 agent 闭环自动化平台。

V2 不再按“补几个功能点”定义，而按“是否能稳定完成复杂任务闭环”定义。判断 V2 是否成立，不看是否新增了聊天、图片或 GitHub 某个单点能力，而看系统是否具备以下特征：

- 能把复杂任务拆解成多阶段、多子任务执行
- 能让 OpenClaw 自动管理多 agent 协作，而不是只跑单 agent 主链路
- 能通过聊天或 bot-view 观察运行状态、介入流程、追溯证据
- 能在 Azure DevOps 之外接入 GitHub 等工作流来源
- 能处理图片、附件和多渠道输入输出
- 能支持长期工程化运维，包括重启恢复、技能分发、配置复制和版本演进

## V2 版本目标

### 目标 1：真正复杂任务闭环

系统必须能处理跨多个文件、多个阶段、多个反馈回路的任务，而不是只做一次性线性修改。

典型任务包括：

- 中等规模功能开发
- 跨模块缺陷修复
- CI 故障恢复与再验证
- 评审意见分批修复
- 带截图或图片证据的问题定位

### 目标 2：统一工作流状态机

V2 必须从“单 run 状态”演进到“父子 run 图 + 阶段状态机 + 可恢复检查点”。

系统需要统一承载：

- 任务主链路
- PR feedback 修复链路
- CI recovery 链路
- 聊天追加指令链路
- 人工接管 / 恢复 / 重试链路

### 目标 3：可视化运行面

V2 必须提供两类观察和交互入口：

- 聊天入口：通过 Rocket.Chat、Weixin 等渠道与 AI / 任务运行交互
- bot-view：查看当前 run、子任务、agent、日志、工件、状态迁移和阻塞点

bot-view 在 V2.0 先做只读状态面，在 V2.1 以后支持受控交互。

### 目标 4：OpenClaw 自动多 agent 管理

V2 必须把 OpenClaw 从“会话 + 单条 flow 编排”提升为“多 agent 任务控制平面”的核心。

至少需要具备：

- 任务拆解
- agent 角色分配
- 子任务工件汇聚
- reviewer / fixer / verifier 回路
- 失败 agent 重试或升级人工

### 目标 5：多渠道、多工作流、多模态

V2 不能绑定 Azure DevOps 单一来源，也不能只支持纯文本任务。

V2 至少要扩展到：

- DevOps / SCM：Azure DevOps + GitHub
- 渠道：Rocket.Chat + Weixin
- 模态：文本 + 图片 + 附件元数据

### 目标 6：长期工程化与 Skill 分发

V2 必须支持长周期维护和快速复制部署：

- 稳定默认配置
- 可模板化部署
- Skill 包版本化与分发
- 运行证据和审计长期留存
- 配置演进不依赖人工逐台复制大文件

## 非目标

V2 不以以下目标为成功前提：

- 从零构建一个新的通用 Agent 平台以替代 OpenClaw
- 替代 Azure DevOps / GitHub 作为源事实系统
- 在 V2.0 就完成多租户 SaaS、组织级 IAM / SSO、复杂审批系统
- 在没有人工策略护栏的前提下默认自动合并到主分支
- 为所有聊天平台先做统一抽象再落地能力
- 引入笨重外部工作流引擎取代当前轻量 runtime

## 目标用户与使用场景

### 用户角色

- 平台操作者：部署、配置、升级、审计 ClawHarness
- 研发负责人：把复杂任务交给系统，并查看进度、风险和阻塞
- 评审 / 维护者：在 PR、CI、聊天中给出反馈并触发续跑
- AI 运行监督者：通过 bot-view 或聊天命令查看 agent 细节、介入和恢复

### 核心场景

- 从 Azure DevOps 复杂工作项触发多 agent 实现并自动开 PR
- 从 GitHub issue 触发同一套复杂任务闭环
- 在 Rocket.Chat / Weixin 中查询运行状态、补充约束、暂停或恢复任务
- 上传截图后，由系统识别图片信息并进入修复流程
- 在 PR 评论或 CI 失败后，恢复到同一父 run 继续执行
- 服务重启后恢复长任务，不重复创建分支、PR 或子任务

## 核心能力分层

### 1. Orchestration Core

V2 的最核心变化不是增加 provider，而是把编排核心从“单次任务流程”升级为“可恢复的复杂任务引擎”。

必须新增或演进的能力：

- `RunGraph`：父 run、子 run、阶段节点、依赖关系
- `Checkpoint`：在 planning、coding、review、repair、publish 等阶段持久化恢复点
- `Artifact Catalog`：计划、评论、检查结果、图片、日志、链接的统一挂载
- `Event Timeline`：所有状态迁移、agent 事件、人工指令、provider 事件统一进时间线
- `Policy Gates`：发布前检查、人工批准、风险升级、预算控制
- `Replay Safety`：重复 webhook、重放命令、服务重启都不产生重复副作用

### 2. Agent Runtime

V2 需要显式支持多 agent，而不是把复杂性压在一个 prompt 里。

能力要求：

- 任务拆解为多个可验证子任务
- agent 角色体系，例如 planner、executor、reviewer、verifier、repairer
- agent 级工件上报，包括总结、变更文件、检查、风险、后续建议
- 子任务结果回收与主任务汇总
- 根据任务类型自动选择 skill
- agent 失败后的重试、替补、升级人工

### 3. Interaction & Observability

V2 需要把“系统正在做什么”变成第一等能力。

能力要求：

- bot-view 展示 run graph、当前阶段、agent 树、最近事件、关键工件、外部链接
- 聊天命令支持 `status`、`detail`、`pause`、`resume`、`add-context`、`escalate`
- 审计事件支持按 task、run、PR、CI、agent、channel 查询
- 长任务支持可追踪的心跳、失败原因、阻塞点和恢复建议
- 重要展示默认是摘要化和脱敏的，避免泄漏原始密钥、敏感 prompt、未授权工件

### 4. Integration & Skills

V2 要保持共享编排核心稳定，同时扩展集成面。

能力要求：

- Azure DevOps 与 GitHub 共用同一套核心工作流状态机
- Rocket.Chat 与 Weixin 共用同一套聊天命令语义
- 图片与附件进入统一工件模型
- Skill 支持版本、来源、启用条件、审计记录和回滚
- 部署层支持稳定默认参数和最小复制成本

## 系统架构草图

```text
Task Source / Chat / Bot-View / Webhook / Manual Trigger
  -> Ingress Normalizer
  -> RunGraph + Event Store + Artifact Catalog
  -> Orchestration State Machine
  -> OpenClaw Control Plane
  -> Multi-Agent Runtime
  -> Provider Adapters
       -> Azure DevOps
       -> GitHub
       -> Rocket.Chat
       -> Weixin
  -> Evidence / Audit / Bot-View API
```

## 关键设计原则

1. OpenClaw 继续作为 AI 控制平面，不再另造一套 Agent 平台。
2. ClawHarness runtime 负责持久化、恢复、事件编排和策略护栏。
3. 复杂任务必须拆成可观察、可恢复、可审计的子任务图。
4. bot-view 是运行面与证据面，不是第二套业务编排器。
5. flow、skill 与状态机要保持 provider-neutral，供应商差异收敛在适配器层。
6. 多渠道交互先统一命令语义，再按渠道特性逐步扩展体验。
7. 图片、附件、评论、日志都进入统一工件模型，而不是散落在各 provider 私有字段中。
8. 部署与配置默认追求“少量稳定字段 + 模板渲染”，避免复制大块版本敏感配置。

## 目录演进建议

基于当前仓库，V2 建议按以下方向演进：

- `run_store/`
  - 从单 run 存储扩展到 `RunGraph`、事件表、工件索引、恢复游标
- `harness_runtime/`
  - 从线性 orchestrator 扩展到统一状态机、agent 调度入口、聊天命令入口、bot-view API
- `openclaw-plugin/`
  - 从单 flow / skill 组合扩展到多 agent 角色模板、可恢复工作流编排、技能分发入口
- `ado_client/`
  - 保留为 Azure DevOps adapter 基线
- `github_client/`
  - 新增 GitHub issue / PR / checks adapter
- `channel_gateway/` 或等价模块
  - 新增 Rocket.Chat / Weixin 命令适配与消息归一化
- `artifact_store/` 或等价模块
  - 新增图片、日志、计划、评论、检查结果统一索引
- `bot_view/` 或等价前后端模块
  - 新增状态查询、工件浏览、人工操作入口
- `deploy/`
  - 补齐一键部署、默认 provider 参数模板、V2 新模块健康检查

## 版本拆分与里程碑

### V2.0 Core

目标：

- 完成复杂任务闭环最小核心
- 把 V1 线性 run 演进为父子 run 图与统一状态机
- 让 OpenClaw 具备自动多 agent 协作基础
- 提供只读 bot-view

范围：

- `RunGraph`、`Checkpoint`、`Artifact Catalog`
- planner / executor / reviewer / verifier 基本多 agent 编排
- Azure DevOps 复杂任务闭环
- PR feedback / CI recovery 纳入统一状态机
- bot-view 只读状态页
- 重启恢复与重复事件幂等

退出标准：

- 能完成一个真实复杂 Azure DevOps 任务，从 work item 到 PR
- 运行中至少出现两个以上子任务 agent，并且状态、工件、检查可见
- PR feedback 与 CI failure 能恢复到同一父 run
- 服务重启后可从检查点恢复，且不重复开 PR

### V2.1 Channels

目标：

- 让系统可从聊天渠道观察、补充上下文和进行受控操作
- 引入图片输入输出

范围：

- Rocket.Chat 命令与状态查询
- Weixin channel 接入
- bot-view 基础交互，例如 pause、resume、retry、escalate
- 图片上传、图片识别、图片作为任务工件进入闭环

退出标准：

- 聊天中可查看状态、补充约束、触发恢复
- bot-view 中可执行基础人工介入操作
- 至少一个图片场景从输入到修复建议闭环跑通

### V2.2 Providers

目标：

- 把核心闭环从 Azure DevOps 扩展到 GitHub

范围：

- GitHub issue / PR / checks adapter
- Provider-neutral 的任务、PR、CI 语义映射
- GitHub 侧主链路、评审恢复、CI 恢复

退出标准：

- 同一套核心工作流可以同时承载 Azure DevOps 与 GitHub
- GitHub 真实 issue 到 PR 的闭环跑通
- GitHub review comment 和 checks failure 的恢复链路跑通

### V2.3 Skills

目标：

- 完成长期工程化所需的 skill 分发、模板复制和策略审计

范围：

- Skill registry / skill pack
- Skill 版本、启用条件、来源、审计
- 项目级部署模板与默认配置包
- 团队级最佳实践和长期运维手册

退出标准：

- 新项目能用模板包快速部署出一套可运行实例
- Skill 自动选择可解释、可审计、可回滚
- 版本升级不需要人工维护大块 `config.toml` / `auth.json`

## V2 成功定义

V2 最终收口必须满足以下结果：

- 可以稳定处理真实复杂工程任务，而不是只有 happy path
- 可以让人通过聊天和 bot-view 明确看到“当前在做什么、做到哪一步、为什么卡住”
- 可以让 OpenClaw 自动管理多 agent，而不是只做单 agent 转发
- 可以在 Azure DevOps 与 GitHub 两种工作流中复用核心能力
- 可以处理图片或截图类输入，并把其纳入统一工件与审计
- 可以通过模板化配置快速复制部署，降低维护成本

## 主要风险与依赖

### 风险

- 多 agent 增加状态复杂度，若没有清晰的 run graph 和 checkpoint，系统会很难恢复
- 聊天与 bot-view 引入新的交互入口，若权限边界不清晰，容易造成误操作
- GitHub 与 Azure DevOps 的事件语义不同，若适配层边界不清晰，会污染核心流程
- Weixin 渠道通常更依赖外部 bridge 或 UI 自动化，稳定性和合规性都要单独审视
- 图片支持会带来存储、脱敏、大小限制和可审计性要求
- 长任务、多 agent 和多 provider 会显著提高成本控制与资源回收难度

### 依赖

- OpenClaw 需要能稳定承载多 agent 管理与可恢复会话
- Codex / 上游模型接口需要保持可自动化调用
- Azure DevOps 与 GitHub 需要稳定 webhook / token / API 配置
- bot-view 需要一套可读运行态与工件的查询接口
- 部署层需要继续坚持“模板渲染 + 稳定字段”的复制策略

## 实施顺序建议

1. 先做 V2.0 Core，把复杂任务闭环和运行时状态机打稳。
2. 再做 V2.1 Channels，把观察和人工介入面补齐。
3. 再做 V2.2 Providers，把核心能力扩展到 GitHub。
4. 最后做 V2.3 Skills，把模板化复制、Skill 分发和长期维护标准化。

## 当前结论

截至 `2026-04-05`，ClawHarness 已完成 V1 的真实主闭环验证。V2 的首要工作不是继续堆单点能力，而是先把复杂任务的编排核心、可观察性和多 agent 运行面建立起来。后续所有渠道、图片、GitHub 和 skill 分发能力，都应建立在这个核心之上，而不是反过来驱动架构。
