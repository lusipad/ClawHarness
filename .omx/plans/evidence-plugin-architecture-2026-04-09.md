# ClawHarness 插件边界改造证据

日期：2026-04-09
范围：plugin / skill / workflow 分层收口

## 提交链

- `2f2d1a8`：制定可闭环实施计划与验收规范
- `5f61885`：引入 canonical skill source，并保留 legacy 兼容加载
- `9ba224c`：引入 manifest-driven capability registry，先落 task-provider
- `53df8f3`：把 workflow 收缩为 `skill_id` / `capability_id` 引用层
- `288286d`：增加 OpenClaw 兼容投影脚本与投影一致性校验
- `b99c5e6`：补充职责边界架构文档

## 结构性结果

### 1. 单一 Skill 真源

- canonical source：`skills/core/`
- compatibility mirror：`openclaw-plugin/skills/`
- runtime 默认优先读取 canonical source，缺失时回退 legacy 路径

### 2. 能力扩展开始走 registry

- `harness_runtime/capability_registry.py`
- `harness_runtime/provider_factories.py`
- `harness_runtime/capabilities/builtin-task-providers.json`

当前已落地 task-provider 这一类 capability。

### 3. workflow 不再保存第二份真文

- `openclaw-plugin/flows/task-run.yaml`
- `openclaw-plugin/flows/pr-feedback.yaml`
- `openclaw-plugin/flows/ci-recovery.yaml`

这些 flow 现在只保留 orchestration references，不再承载第二份 skill 正文。

### 4. 文档边界已固定

- `docs/plugin-boundary.md`
- `openclaw-plugin/runtime/README.md`
- `openclaw-plugin/hooks/README.md`
- `skills/README.md`
- `skills/core/README.md`
- `openclaw-plugin/skills/README.md`

## 验证命令与结果

### Projection 一致性

```powershell
python -m harness_runtime.skill_projection --check
```

结果：

- `projection_ok D:\Repos\claw_az\openclaw-plugin\skills\registry.json`

### Skill 投影专项测试

```powershell
python -m unittest tests.test_skill_projection -v
```

结果：

- `3/3` 通过

### 全量单元测试

```powershell
python -m unittest discover -s tests -v
```

结果：

- `160/160` 通过

### 语法编译

```powershell
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
```

结果：

- 通过

## AI SLOP CLEANUP REPORT

Scope:

- `harness_runtime/skill_projection.py`
- `tests/test_skill_projection.py`
- `docs/plugin-boundary.md`

Behavior Lock:

- `python -m unittest tests.test_skill_projection -v`
- `python -m harness_runtime.skill_projection --check`

Cleanup Plan:

- 只处理低风险重复逻辑
- 不改动 registry schema
- 不扩大到 runtime 主状态机或 provider 逻辑

Passes Completed:

1. Dead code deletion：无
2. Duplicate removal：抽出 `_projected_root(...)`，去掉 `project` / `verify` 中重复的目标目录解析
3. Naming / error handling cleanup：无新增需求
4. Test reinforcement：保留投影漂移检测测试与 `--check` 实测

Quality Gates:

- Regression tests: PASS
- Typecheck / compile: PASS
- Tests: PASS
- Projection drift check: PASS

## 当前结论

本轮 plugin / skill / workflow 改造已经形成可验证闭环：

- skill 真源唯一
- capability registry 已落地第一类能力
- workflow 已降级为引用层
- OpenClaw Shell 不再承载系统级交付真相

## 备注

- `deploy/package/export_deploy_bundle.py` 当前仍有独立进行中的改动，本轮未把“导出前自动执行 skill projection”强行混入同一提交；当前发布前流程应先运行 `python -m harness_runtime.skill_projection --check`。
