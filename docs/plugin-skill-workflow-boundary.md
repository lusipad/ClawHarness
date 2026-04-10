# ClawHarness 插件、Skill 与 Workflow 边界说明

日期：2026-04-09
状态：V3 已完成基线

## 目的

这份文档说明 ClawHarness 当前的三层边界，避免再次把 `Plugin`、`Skill`、`Workflow` 混成一套系统真相。

核心原则：

1. `Plugin` 只扩展能力，不复制业务闭环真相。
2. `Skill` 只有一套 canonical source。
3. `Workflow` 只保存阶段与引用，不保存第二份 skill 正文。

## 三层职责

### 1. ClawHarness Core

ClawHarness Core 负责：

- 任务到 PR 的闭环状态机
- provider-neutral 的运行时与审计
- skill 选择、skill 审计与默认加载
- capability registry 与内建 provider 装配

当前对应目录：

- `harness_runtime/`
- `run_store/`
- `workflow_provider/`
- `skills/`

### 2. OpenClaw Shell

OpenClaw Shell 负责：

- OpenClaw 插件入口
- Shell 侧 hooks / flow 参考定义
- OpenClaw 消费所需的 skill 兼容镜像
- UI / bot-view / chat 等交互与宿主扩展面

当前对应目录：

- `openclaw-plugin/`

### 3. Codex Executor

Codex Executor 负责：

- 实际代码修改
- 本地检查与结果输出
- 结构化 agent 结果返回

当前对应目录：

- `codex_acp_runner/`

## Skill 真源

当前 canonical skill source 位于：

- `skills/core/registry.json`
- `skills/core/<skill-id>/SKILL.md`

运行时默认优先读取 canonical source，对应实现位于：

- `harness_runtime/skill_registry.py`

兼容规则：

- 优先读取 `skills/core/registry.json`
- 缺失时回退到 `openclaw-plugin/skills/registry.json`
- 两者都不存在时，回退为 `missing` 安全默认路径

## OpenClaw 侧 Skill 镜像

`openclaw-plugin/skills/` 不是长期手工维护真源，而是 OpenClaw 消费用的兼容镜像。

当前投影与校验入口：

- 生成：`python -m harness_runtime.skill_projection`
- 校验：`python -m harness_runtime.skill_projection --check`

对应实现位于：

- `harness_runtime/skill_projection.py`

## Workflow 边界

OpenClaw flow 文件当前只保留引用关系，不再承担 skill 正文职责。

当前对应文件：

- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`

当前约定：

- `skill_refs` 只写 `skill_id`
- `capability_refs` 只写 `capability_id`
- flow 负责阶段顺序与引用，不复制 `SKILL.md` 正文

## Capability 边界

ClawHarness 现在通过 capability registry 装配内建能力。

当前对应文件：

- `harness_runtime/capability_registry.py`
- `harness_runtime/capabilities/builtin-task-providers.json`
- `harness_runtime/capabilities/builtin-executors.json`
- `harness_runtime/capabilities/builtin-notifiers.json`
- `harness_runtime/provider_factories.py`
- `harness_runtime/runtime_factories.py`

当前已经落地的方向是：

- 能力通过 manifest/registry 声明
- runtime 装配 task-provider / executor / notifier
- 差异尽量收敛在 factory / adapter 边界

当前默认运行基线还包括：

- `local-task` 作为默认 provider
- `codex-cli` 作为默认 executor
- `shell disabled` 作为默认启动模式
- OpenClaw 仅在显式启用时作为可选壳层叠加

## 当前仍需保持的纪律

后续继续演进时，遵守以下规则：

1. 新增或修改 skill 时，先改 `skills/core/`。
2. 不要把 `openclaw-plugin/skills/` 当成手工真源。
3. 不要在 flow 文件里重新写长 prompt。
4. 不要在 hooks 或 plugin runtime 里复制 Core 的状态机真相。
5. 新能力优先走 capability registry，而不是继续堆散落的宿主判断分支。

## 运维建议

如果你要排查 skill 相关问题，优先按这个顺序看：

1. `skills/core/registry.json`
2. `skills/core/<skill-id>/SKILL.md`
3. `harness_runtime/skill_registry.py`
4. `harness_runtime/skill_projection.py`
5. `openclaw-plugin/skills/README.md`

如果你要排查插件/能力装配问题，优先按这个顺序看：

1. `harness_runtime/capability_registry.py`
2. `harness_runtime/capabilities/builtin-task-providers.json`
3. `harness_runtime/provider_factories.py`
4. `harness_runtime/main.py`
