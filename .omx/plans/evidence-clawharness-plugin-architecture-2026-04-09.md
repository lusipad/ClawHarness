# ClawHarness 插件边界收口证据

日期：2026-04-09
对应计划：

- `.omx/plans/prd-clawharness-plugin-architecture-2026-04-09.md`
- `.omx/plans/test-spec-clawharness-plugin-architecture-2026-04-09.md`

## 结论

本轮执行确认：插件边界改造计划里的核心收敛已经在当前代码基线上成立，当前提交补齐的是：

1. OpenClaw skill mirror README 模板与实际镜像的一致性。
2. canonical skill ownership 的收口说明。
3. 当前边界状态的仓库内证据文档。

## 当前已确认的实现事实

### 1. canonical skill source

当前 canonical source 位于：

- `skills/core/registry.json`
- `skills/core/<skill-id>/SKILL.md`

运行时优先读取实现位于：

- `harness_runtime/skill_registry.py`

### 2. OpenClaw compatibility mirror

当前 OpenClaw skill 镜像位于：

- `openclaw-plugin/skills/`

镜像生成与漂移校验位于：

- `harness_runtime/skill_projection.py`
- `tests/test_skill_projection.py`

### 3. workflow 已为引用层

当前 flow 文件使用引用型结构：

- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`

对应验证位于：

- `tests/test_workflow_references.py`

### 4. capability registry 已接入主运行链路

当前 capability registry 相关文件：

- `harness_runtime/capability_registry.py`
- `harness_runtime/capabilities/builtin-task-providers.json`
- `harness_runtime/main.py`
- `tests/test_capability_registry.py`

## 本轮收口文件

- `harness_runtime/skill_projection.py`
- `tests/test_skill_projection.py`
- `skills/README.md`
- `.omx/plans/evidence-clawharness-plugin-architecture-2026-04-09.md`

## 验证命令

### 1. 重新生成 OpenClaw skill 镜像

```powershell
python -m harness_runtime.skill_projection
```

结果：

- `projected_skills openclaw-plugin/skills/registry.json`

### 2. 校验镜像无漂移

```powershell
python -m harness_runtime.skill_projection --check
```

结果：

- `projection_ok openclaw-plugin/skills/registry.json`

### 3. 全量单元与集成测试

```powershell
python -m unittest discover -s tests -v
```

结果：

- `160/160` 通过

### 4. 语法编译检查

```powershell
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
```

结果：

- 通过

## 边界结论

当前仓库的职责边界应按以下方式理解：

- `ClawHarness Core`：持有交付闭环真相、状态机、审计、checkpoint、canonical skill source。
- `OpenClaw Shell`：持有宿主入口、hook、flow 引用和兼容镜像。
- `Codex Executor`：负责实际编码、检查和结构化结果返回。

## 后续纪律

后续继续演进时，保持以下约束：

1. 新增或修改 skill 时，先改 `skills/core/`。
2. 不要把 `openclaw-plugin/skills/` 当成手工真源。
3. 不要在 workflow 文件里再次写一份 canonical 指令正文。
4. 新 capability 优先走 registry / manifest 路径，而不是在 shell 层复制业务真相。
