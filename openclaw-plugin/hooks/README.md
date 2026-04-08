# `openclaw-plugin/hooks`

状态：骨架已建立

计划中的 hook 面：
- task-ingest
- pr-feedback
- ci-failure

这些 hooks 负责归一化入站事件、持久化运行时元数据，并唤醒或继续执行正确的 OpenClaw flow。

边界说明：

- hooks 负责 Shell 侧入口与唤醒
- Core 状态机与 skill 真源不在这里维护
- 如需扩展系统能力，优先通过 capability registry 扩展，而不是在 hooks 内复制业务真相
