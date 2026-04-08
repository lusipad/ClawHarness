# OpenClaw Skill 兼容镜像

`openclaw-plugin/skills/` 是从 `skills/core/` 投影出来的兼容目录。

规则：

- 不要在这里手工维护 skill 真文。
- `openclaw-plugin/openclaw.plugin.json` 继续通过这里向 OpenClaw 暴露 skills。
- 变更 canonical source 后，重新运行 `python -m harness_runtime.skill_projection`。
- 在 CI 或发布前，可用 `python -m harness_runtime.skill_projection --check` 校验这里没有漂移。
