# `openclaw-plugin/runtime`

状态：骨架已建立

用途：
- 在插件层组合运行时存储、加锁、去重和审计辅助能力

规划中的子区域：
- db
- locks
- events
- audit

实现说明：
- 当前可执行的 bridge/runtime 集成仍位于顶层 Python 包 `harness_runtime/`
- 这样可以让 OpenClaw 原生插件包保持轻量，同时由 webhook bridge 负责 ingress、持久化与唤醒分发
