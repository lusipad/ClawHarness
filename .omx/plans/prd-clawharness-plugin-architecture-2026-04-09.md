# ClawHarness 插件化与单一 Skill 真源改造 PRD

日期：2026-04-09
状态：待执行
配套文档：
- `.omx/plans/test-spec-clawharness-plugin-architecture-2026-04-09.md`
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`

## 背景

当前仓库已经具备可运行的闭环能力，但 `plugin / skill / workflow` 的边界仍然混在一起：

- `harness_runtime/skill_registry.py` 当前默认从 `openclaw-plugin/skills/registry.json` 读取 skill 注册表。
- `harness_runtime/orchestrator.py` 会把选中的 skill 注入执行 prompt。
- `openclaw-plugin/openclaw.plugin.json` 与 `openclaw-plugin/index.ts` 目前承担的是 OpenClaw 宿主插件入口职责。
- `openclaw-plugin/skills/` 同时保存了 skill 注册表与 `SKILL.md` 正文。
- `openclaw-plugin/flows/*.yaml` 又在 flow 中直接声明 `skills`。

继续沿着这个方向扩展，后面会出现三个问题：

1. OpenClaw 插件层演化成第二套 skill 真源。
2. workflow 文件开始兼任编排定义和 prompt 仓库。
3. ClawHarness Core、OpenClaw Shell、Codex Executor 的职责继续重叠。

本次改造的目标不是“增加更多插件”，而是收敛出一个轻量、可复制、长期可维护的体系：

- `ClawHarness Core` 负责工作流闭环、状态机、策略和审计。
- `OpenClaw Shell` 负责 UI、聊天、bot-view、人工干预与插件宿主。
- `Codex Executor` 负责实际编码和验证。

## 产品目标

建立一套可渐进迁移的架构，使系统满足以下原则：

1. 全系统只有一个 canonical skill source。
2. 插件只扩展 capability，不复制 workflow 或 skill 正文。
3. workflow 只引用 `skill_id` 与 `capability_id`，不保存第二份指令真文。
4. 迁移过程必须保持当前 Azure / GitHub / local-task 链路可运行。
5. 每一步改造都能独立闭环、验证并单独提交。

## 非目标

本轮改造不以以下事项为目标：

- 不重写现有 orchestrator 主链路。
- 不引入新的重量级工作流引擎。
- 不同时重做所有 provider、chat、bot-view 细节体验。
- 不要求第一步就删除全部历史兼容层。

## 设计决策

### 决策 1：Plugin / Skill / Workflow 三分

- `Plugin`：能力扩展层，只声明和实现 capability。
- `Skill`：唯一内容真源，保存 `skill_id`、版本、元数据与正文。
- `Workflow`：核心编排层，只引用 `skill_id`、`capability_id` 与状态迁移。

### 决策 2：保持单一 Skill 真源

canonical skill source 应迁出 `openclaw-plugin/skills/`，改为由 ClawHarness Core 直接拥有，例如：

- `skills/core/`
- 或 `skill_packs/core/`

OpenClaw 需要的 skill 目录只能是投影产物或只读镜像，不能再作为手工维护真源。

### 决策 3：插件清单走 manifest 驱动

插件应使用统一 manifest 声明：

- 插件标识
- capability 类型
- capability 列表
- 配置 schema
- 宿主约束

不允许通过宿主核心代码中持续增加 `if provider == ...` / `if channel == ...` 的方式扩展能力。

### 决策 4：迁移必须兼容旧路径

迁移阶段需要兼容旧的 `openclaw-plugin/skills/registry.json` 读取方式，直到 canonical source、投影生成与文档全部落稳，再移除旧路径。

## 验收标准

### AC-01：单一 Skill 真源

- 系统存在明确的 canonical skill source 目录。
- skill 正文不再以 OpenClaw 插件目录作为唯一手工维护入口。
- runtime 审计记录保留 `skill_id`、`version`、`source`。

### AC-02：OpenClaw 插件层收缩为宿主能力

- `openclaw-plugin/` 只承担 OpenClaw 宿主插件、工具入口、UI 或投影资源职责。
- 不再把其定义为系统级 skill 真源。

### AC-03：Workflow 不再保存第二份 Skill 正文

- workflow 只引用 `skill_id` 和 `capability_id`。
- workflow 中不复制 `SKILL.md` 的正文或等价长指令。

### AC-04：能力扩展通过 manifest + registry

- provider、chat、ui、review 等能力能通过统一注册方式发现。
- 核心运行时代码不依赖散落的能力分支来完成扩展。

### AC-05：兼容现有闭环

- `azure-devops`、`github`、`local-task` 现有测试保持通过。
- 关键离线路径仍可执行一次 task -> branch -> review artifact 的闭环。

### AC-06：每一步可闭环提交

- 每一步都有明确输入、输出、验证命令和提交边界。
- 任一步完成后，主分支保持可测试、可运行、不留半迁移状态。

## 分阶段实施计划

### Step 1：架构基线与目录契约

目标：
- 把目标边界固化成文档和最小目录契约，不改运行时行为。

改动范围：
- 新增架构说明文档。
- 定义 canonical skill source 目录与插件 manifest 草案。
- 标注 `openclaw-plugin/skills` 的未来角色为“投影产物/兼容目录”。

主要文件：
- `.omx/plans/prd-clawharness-plugin-architecture-2026-04-09.md`
- `.omx/plans/test-spec-clawharness-plugin-architecture-2026-04-09.md`
- 后续执行时新增 `docs/` 或等价架构文档目录

闭环标准：
- 文档清楚定义边界、迁移顺序和退出条件。
- 不影响任何现有运行与测试。

提交边界：
- 只提交规划与架构文档。

建议提交意图：
- `Define the plugin-skill-workflow boundary before refactoring runtime ownership`

### Step 2：建立 canonical skill source 与兼容加载

目标：
- 建立新的 canonical skill source。
- runtime 优先读取 canonical source，同时兼容旧路径。

改动范围：
- 新增 canonical skill 目录与 schema。
- 调整 `harness_runtime/skill_registry.py`。
- 为 skill source 解析与兼容加载补测试。

主要文件：
- `harness_runtime/skill_registry.py`
- `tests/test_harness_runtime.py`
- `tests/test_task_orchestrator.py`
- 新增 `skills/` 或 `skill_packs/` 目录

闭环标准：
- 新旧 skill source 至少一条链路可成功加载。
- 现有单元测试继续通过。

提交边界：
- 只提交 canonical source 与加载兼容层，不改 OpenClaw 投影生成。

建议提交意图：
- `Move skill ownership into ClawHarness core without breaking the existing runtime`

### Step 3：生成 OpenClaw skill 投影

目标：
- 让 OpenClaw 所需的 `skills/registry.json` 与 `SKILL.md` 从 canonical source 自动生成或同步。

改动范围：
- 新增生成脚本或导出逻辑。
- 把 `openclaw-plugin/skills/` 明确标记为生成目录或兼容镜像。
- 增加生成一致性测试。

主要文件：
- `openclaw-plugin/skills/`
- `deploy/package/export_deploy_bundle.py`
- 新增生成脚本目录
- 新增对应测试

闭环标准：
- 可以从 canonical source 生成 OpenClaw 消费产物。
- 生成结果与 runtime 可消费格式保持一致。

提交边界：
- 只提交生成链路和兼容说明，不改 workflow 语义。

建议提交意图：
- `Project canonical skills into OpenClaw consumables instead of hand-maintaining a second source`

### Step 4：引入 capability plugin manifest 与注册表

目标：
- 把 provider、chat、ui、review 等扩展面收敛成统一 capability plugin 模型。

改动范围：
- 定义 plugin manifest schema。
- 新增 capability registry。
- 给现有内建能力建立适配注册入口。

主要文件：
- `harness_runtime/config.py`
- `harness_runtime/main.py`
- `harness_runtime/bridge.py`
- `workflow_provider/`
- `openclaw-plugin/openclaw.plugin.json`

闭环标准：
- 至少一类 capability 可以通过新 registry 被发现和使用。
- 旧配置方式仍可工作。

提交边界：
- 只提交 registry 与至少一类能力接入，不同时重构全部能力。

建议提交意图：
- `Introduce a manifest-driven capability registry without breaking built-in providers`

### Step 5：workflow 只引用 skill_id / capability_id

目标：
- 把 workflow 从“混合定义层”收缩成纯编排引用层。

改动范围：
- 调整 `openclaw-plugin/flows/*.yaml` 或等价 workflow 定义。
- runtime 只消费引用信息，不依赖第二份正文。
- 为 workflow 解析和执行路径补测试。

主要文件：
- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`
- `harness_runtime/orchestrator.py`

闭环标准：
- workflow 文件中不再承担 skill 正文角色。
- 现有 task / pr-feedback / ci-recovery 路径测试保持通过。

提交边界：
- 只提交 workflow 引用化和相关兼容层。

建议提交意图：
- `Reduce workflows to orchestration references instead of duplicated instruction sources`

### Step 6：收缩 OpenClaw Shell 角色并清理兼容债务

目标：
- 把 OpenClaw 的定位最终固定为 UI / chat / bot-view / shell。
- 删除已经不再需要的旧真源入口和重复说明。

改动范围：
- 更新 `README.md`、`README.zh-CN.md`、部署文档。
- 清理旧 skill 路径的默认依赖。
- 保留必要兼容提示与迁移说明。

主要文件：
- `README.md`
- `README.zh-CN.md`
- `deploy/README.md`
- `openclaw-plugin/runtime/README.md`
- `openclaw-plugin/hooks/README.md`

闭环标准：
- 文档、代码、目录职责一致。
- 新部署默认走 canonical source + projection。

提交边界：
- 只提交角色收口与文档升级，不夹带新行为特性。

建议提交意图：
- `Finish the ownership split so OpenClaw remains a shell and ClawHarness owns delivery truth`

### Step 7：真实链路回归与发布收口

目标：
- 用最小真实链路证明改造没有破坏现有系统。

改动范围：
- 跑完整测试。
- 跑一次 `local-task` 离线路径。
- 如果环境允许，再补一条 live provider 验证。

主要文件：
- 测试文件与必要修复文件
- `.omx/plans/evidence-*` 新证据文档

闭环标准：
- 测试通过。
- 至少一条真实闭环证据完成更新。

提交边界：
- 只提交最终兼容修复和证据文档。

建议提交意图：
- `Prove the architecture split with regression coverage and a real end-to-end run`

## 验证策略

每一步完成后，至少执行与该步相称的验证：

- 文档步：文件存在性、自洽审查、引用路径检查
- Python 步：`python -m unittest discover -s tests -v`
- 语法步：`python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests`
- 离线闭环步：`python -m harness_runtime.main --provider-type local-task --task-id <sample>`
- OpenClaw 投影步：生成脚本执行 + 生成物一致性检查

## 风险与缓解

### 风险 1：迁移期间出现双写

风险：
- canonical source 和 `openclaw-plugin/skills/` 同时被手工维护，导致漂移。

缓解：
- 一旦 Step 3 落地，明确把 OpenClaw skill 目录改为生成产物。

### 风险 2：workflow 与 runtime 同时重构导致链路断裂

风险：
- 如果在同一步里既改 skill source 又改 workflow 消费方式，容易一次改坏两层。

缓解：
- 先完成 source 收敛，再做 workflow 引用化。

### 风险 3：manifest 设计过重

风险：
- 为了“可扩展”而引入过多抽象，反而让轻量部署变重。

缓解：
- 先只支持少数 capability 类型：`task-provider`、`chat-channel`、`ui-surface`、`review-publisher`、`executor`。

## 发布判定

本轮改造完成的标志不是“多了几个插件”，而是以下四点同时成立：

1. skill 真源唯一。
2. workflow 只做引用。
3. OpenClaw 不再承载系统级交付真相。
4. 现有闭环仍然可跑、可测、可部署。

## 提交策略

每一步结束后立即提交，提交时遵循仓库的 Lore Commit Protocol：

- intent line 只写“为什么”
- body 记录取舍和兼容策略
- trailers 至少包含：
  - `Confidence:`
  - `Scope-risk:`
  - `Directive:`
  - `Tested:`
  - `Not-tested:`

若工作区存在无关脏改动，则使用 path-limited commit，只提交该步骤相关文件。
