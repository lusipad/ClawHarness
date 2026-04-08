# ClawHarness Canonical Skills

这个目录是 ClawHarness 的 canonical skill source。

当前约定：

- `skills/core/registry.json` 是运行时优先读取的 skill registry。
- `skills/core/<skill-id>/SKILL.md` 保存每个 skill 的正文真源。
- `openclaw-plugin/skills/` 暂时保留为 legacy 兼容目录。

迁移阶段要求：

- 新增或修改 skill 时，先更新这里。
- 不要继续把 `openclaw-plugin/skills/` 当成长期手工维护真源。
- OpenClaw 侧兼容投影由 `python -m harness_runtime.skill_projection` 生成和校验。
