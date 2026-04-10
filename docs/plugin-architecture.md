# ClawHarness 插件与职责边界

日期：2026-04-09
状态：V3 已完成基线

## 一句话原则

- 插件扩能力
- skill 保单源
- workflow 留核心

## 分层职责

### ClawHarness Core

负责：

- task -> branch -> PR -> CI -> feedback -> recovery 的闭环真相
- run graph、checkpoint、审计、策略护栏
- canonical skill source
- provider-neutral 的状态机与工件模型

不负责：

- Web UI 外壳
- 聊天交互宿主
- 渠道生态本身

### OpenClaw Shell

负责：

- Web/UI/chat 入口
- bot-view 与人工干预入口
- 插件宿主与工具入口
- 对 ClawHarness Core 的兼容消费面

不负责：

- 系统级交付闭环真相
- canonical skill source
- provider-neutral 状态机

### Codex Executor

负责：

- 实际编码、修改仓库、运行检查
- 返回结构化结果、风险和后续动作

不负责：

- 持久化 run 生命周期
- 管理 provider webhook 与外部状态同步

## Plugin / Skill / Workflow 三分

### Plugin

Plugin 只负责 capability 扩展，例如：

- `task-provider`
- `chat-channel`
- `ui-surface`
- `review-publisher`
- `executor`

Plugin 不复制 workflow，不保存系统级 skill 真文。

### Skill

Skill 只有一个手工维护入口：

- `skills/core/`

OpenClaw 侧 `openclaw-plugin/skills/` 只是兼容投影目录。

### Workflow

Workflow 只表达：

- 阶段顺序
- `skill_id`
- `capability_id`
- gate / outcome

Workflow 不保存第二份 skill 正文。

## 当前目录约定

### Canonical source

- `skills/core/registry.json`
- `skills/core/<skill-id>/SKILL.md`

### OpenClaw projection

- `openclaw-plugin/skills/registry.json`
- `openclaw-plugin/skills/<skill-id>/`

### Flow references

- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`

### Built-in capability manifests

- `harness_runtime/capabilities/builtin-task-providers.json`
- `harness_runtime/capabilities/builtin-executors.json`
- `harness_runtime/capabilities/builtin-notifiers.json`

## 维护规则

1. 先改 `skills/core/`
2. 再生成 `openclaw-plugin/skills/`
3. 如需扩展运行能力，先加 capability manifest 和 registry
4. 不要在 workflow 文件里重新写一份 skill 正文

## 当前收口结果

截至 2026-04-09：

- local-first / core-only 已成为默认推荐路径
- OpenClaw Shell 已降级为可选壳层，而不是核心运行前提
- runtime 已优先读取 `skills/core/`
- OpenClaw skills 已可由 canonical source 投影生成
- task-provider / executor / notifier 已进入 manifest-driven registry
- draft flow 已收缩为 `skill_id` / `capability_id` 引用层
