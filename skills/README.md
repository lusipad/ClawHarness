# ClawHarness Canonical Skills

这个目录是 ClawHarness 的 canonical skill source。

当前约定：

- `skills/core/registry.json` 是运行时优先读取的 skill registry。
- `skills/core/<skill-id>/SKILL.md` 保存每个 skill 的正文真源。
- `openclaw-plugin/skills/` 作为 OpenClaw 兼容镜像保留，不再作为手工真源。

维护规则：

- 新增或修改 skill 时，先更新这里。
- 不要继续把 `openclaw-plugin/skills/` 当成长期手工维护真源。
- OpenClaw 侧兼容投影由 `python -m harness_runtime.skill_projection` 生成。
- 在 CI 或发布前，可运行 `python -m harness_runtime.skill_projection --check` 校验镜像没有漂移。
