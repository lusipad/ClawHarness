# ClawHarness 插件化与单一 Skill 真源改造证据

日期：2026-04-09
范围：plugin / skill / workflow 边界收口

## 结论

截至 2026-04-09，ClawHarness 的插件化边界已经具备以下状态：

1. canonical skill source 已在代码中生效。
2. OpenClaw skill 目录已经是兼容镜像，而不是长期手工真源。
3. workflow 已收缩为引用层。
4. capability registry 已落地并进入运行时装配路径。
5. 本轮新增了中文边界说明文档，用于固定当前职责分层。

## 代码证据

### 1. canonical skill source

- `skills/core/registry.json`
- `skills/core/<skill-id>/SKILL.md`
- `skills/README.md`
- `harness_runtime/skill_registry.py`

观察结论：

- 运行时默认优先读取 `skills/core/registry.json`
- 缺失时回退到 `openclaw-plugin/skills/registry.json`
- 两者都不存在时返回 `missing` 安全默认路径

### 2. OpenClaw 侧 skill 镜像

- `harness_runtime/skill_projection.py`
- `openclaw-plugin/skills/README.md`
- `tests/test_skill_projection.py`

观察结论：

- `openclaw-plugin/skills/` 由 `python -m harness_runtime.skill_projection` 投影生成
- `python -m harness_runtime.skill_projection --check` 可校验镜像是否漂移

### 3. workflow 引用化

- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`

观察结论：

- flow 文件使用 `skill_refs`
- flow 文件使用 `capability_refs`
- flow 文件不再保存第二份 skill 正文

### 4. capability registry

- `harness_runtime/capability_registry.py`
- `harness_runtime/capabilities/builtin-task-providers.json`
- `harness_runtime/provider_factories.py`
- `tests/test_capability_registry.py`
- `harness_runtime/main.py`

观察结论：

- 运行时已经通过 capability registry 装配内建 task provider
- 默认内建能力已覆盖 `azure-devops`、`github`、`local-task`

## 本轮新增文档

- `docs/plugin-skill-workflow-boundary.md`

用途：

- 固定 `ClawHarness Core / OpenClaw Shell / Codex Executor` 的职责边界
- 明确 canonical source、compatibility mirror、workflow refs、capability registry 的关系

## 本轮提交

- `2f2d1a8`
  - 规划与测试规范落盘
- `ce5ed6a`
  - 当前职责边界文档化并补强 OpenClaw skill 镜像说明

## 本轮验证

### 1. Python 单元测试

命令：

```powershell
python -m unittest discover -s tests -v
```

结果：

- `158/158` 通过

### 2. 语法编译检查

命令：

```powershell
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
```

结果：

- 通过

### 3. OpenClaw skill 投影一致性检查

命令：

```powershell
python -m harness_runtime.skill_projection --check
```

结果：

- `projection_ok D:\Repos\claw_az\openclaw-plugin\skills\registry.json`

## 剩余事项

本轮未直接提交以下内容：

- 顶层 `README.md`
- `README.zh-CN.md`
- `deploy/README.md`
- `deploy/package/README.md`

原因：

- 这些文件在工作区中已经存在其他未提交改动
- 为避免把无关改动混入本轮边界收口提交，本轮只提交了干净文件与新文档

这不影响当前代码边界本身已经落地，但意味着顶层文档的最终统一说明仍需要在后续单独清理后再收口。
