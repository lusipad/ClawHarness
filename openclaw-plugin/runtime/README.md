# `openclaw-plugin/runtime`

状态：骨架已建立

用途：
- 在 OpenClaw Shell 一侧提供兼容运行面与宿主拼装点
- 不作为 ClawHarness Core 的系统级交付真相来源

规划中的子区域：
- db
- locks
- events
- audit

实现说明：
- 当前可执行的 bridge/runtime 集成仍位于顶层 Python 包 `harness_runtime/`
- 这样可以让 OpenClaw 原生插件包保持轻量，同时由 webhook bridge 负责 ingress、持久化与唤醒分发
- canonical skill source 已迁入 `skills/core/`；OpenClaw 侧只保留兼容投影与消费入口
