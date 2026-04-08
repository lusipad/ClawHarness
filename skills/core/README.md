# Canonical Skill 真源

`skills/core/` 是 ClawHarness 的 canonical skill source。

规则：

- 新增或修改 skill 时，先改这里。
- 保持 `registry.json` 与同级 `SKILL.md` 的内容一致。
- `openclaw-plugin/skills/` 当前只是兼容消费目录，由 `python -m harness_runtime.skill_projection` 生成和校验。
