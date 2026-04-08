# ClawHarness 插件边界与 Skill 所有权

日期：2026-04-09
状态：执行中架构基线

## 目标

把 ClawHarness、OpenClaw、Codex 三者的职责固定下来，避免继续演化出多套平行的 skill、workflow 和状态机真源。

## 分层原则

### ClawHarness Core

职责：

- 工作流闭环
- provider-neutral 状态机
- run / audit / checkpoint / artifact 真相
- canonical skill source
- capability registry

不负责：

- Web UI 外壳
- 聊天会话体验
- 渠道插件宿主体验

### OpenClaw Shell

职责：

- Web/UI/chat 外壳
- bot-view 与人工干预入口
- OpenClaw 宿主插件与工具入口
- 对 ClawHarness Core 的兼容消费面

不负责：

- 任务闭环真相
- provider-neutral 状态机真相
- canonical skill source

### Codex Executor

职责：

- 实际编码执行
- 文件修改
- 检查与结果产出

不负责：

- provider 生命周期
- 持久化 run 真相
- 系统级工作流编排

## 当前目录映射

### canonical source

- `skills/core/`

这里保存 skill registry 与 `SKILL.md` 真文，是系统唯一手工维护的 skill 真源。

### compatibility mirror

- `openclaw-plugin/skills/`

这里是 OpenClaw 侧兼容目录，由 `python -m harness_runtime.skill_projection` 从 `skills/core/` 投影生成和校验。

### capability registry

- `harness_runtime/capabilities/`
- `harness_runtime/capability_registry.py`
- `harness_runtime/provider_factories.py`

这里定义 capability manifest 与内建 provider 的注册入口。

### workflow references

- `openclaw-plugin/flows/*.yaml`

这些 flow 文件只保存阶段顺序、`skill_id` 引用和 `capability_id` 引用，不再承载第二份 skill 真文。

## 维护规则

1. 修改 skill 时，先改 `skills/core/`。
2. 修改后运行 `python -m harness_runtime.skill_projection`。
3. 提交前运行 `python -m harness_runtime.skill_projection --check`。
4. 不要手工维护 `openclaw-plugin/skills/` 里的 skill 真文。
5. 不要在 workflow 文件里复制 skill 正文。

## 当前实现边界

- 任务 provider 已经通过 manifest-driven capability registry 进入运行时。
- OpenClaw 技能目录已经转为 compatibility mirror。
- flow 文件已经降级为 orchestration references。
- `harness_runtime/` 继续承担主状态机、恢复、审计和执行编排。

## 后续约束

- 如果后续要增加 chat、ui、review publisher 等 capability，也应走同一套 registry/manifest 模型。
- 新 capability 可以扩展系统能力，但不能复制 canonical skill source。
- 新文档、部署说明与运维手册都要继续沿用这个分层，不再把 `openclaw-plugin/skills` 描述成系统真源。
