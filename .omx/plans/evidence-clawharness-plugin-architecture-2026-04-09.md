# ClawHarness 插件化与单一 Skill 真源改造证据

日期：2026-04-09
对应计划：
- `.omx/plans/prd-clawharness-plugin-architecture-2026-04-09.md`
- `.omx/plans/test-spec-clawharness-plugin-architecture-2026-04-09.md`

## 结论

当前仓库已经满足这轮改造计划的核心目标：

1. `skills/core/` 是 canonical skill source。
2. `openclaw-plugin/skills/` 是投影出来的 OpenClaw 兼容目录。
3. runtime 默认优先读取 canonical skill registry，并保留 legacy 回退。
4. capability registry 已进入主运行链路。
5. OpenClaw flow 已经收缩为引用层，不再保存 canonical skill 正文。
6. 用户文档已经按新的 ownership 模型完成同步。
7. 已追加一条真实 `local-task` 离线闭环证据，证明当前架构收口没有破坏主链路。

## 静态与回归验证

### 全量单元测试

执行命令：

```powershell
python -m unittest discover -s tests -v
```

结果：

- `153/153` 通过

### 语法编译检查

执行命令：

```powershell
python -m compileall ado_client codex_acp_runner github_client harness_runtime local_client rocketchat_notifier run_store workflow_provider tests
```

结果：

- 通过

### skill projection 一致性检查

执行命令：

```powershell
python -m harness_runtime.skill_projection --check
```

结果：

- 输出 `projection_ok D:\Repos\claw_az\openclaw-plugin\skills\registry.json`

这说明当前仓库中的 `openclaw-plugin/skills/` 与 canonical source 没有漂移。

## 真实离线闭环验证

本轮新增了一次隔离的 `local-task` 真实运行，未修改默认部署配置，也未污染既有离线验证目录。

### 验证输入

临时验证根目录：

- `.tmp/plugin-architecture-live-run/`

任务文件：

- `.tmp/plugin-architecture-live-run/tasks/task-002.md`

源仓库：

- `.tmp/plugin-architecture-live-run/repo/`

执行命令：

```powershell
$env:HARNESS_EXECUTOR_BACKEND='codex-cli'
python -m harness_runtime.main `
  --providers-config .tmp/plugin-architecture-live-run/providers.local-task.yaml `
  --openclaw-config .tmp/plugin-architecture-live-run/openclaw.local.json `
  --policy-config deploy/config/harness-policy.yaml `
  --provider-type local-task `
  --task-id task-002
```

### 运行结果

命令返回：

```json
{
  "run_id": "manual-repo-task-002",
  "status": "awaiting_review",
  "branch_name": "refs/heads/ai/task-002-add-offline-validation-note",
  "pr_id": "local-bc17c8fd",
  "workspace_path": "D:\\Repos\\claw_az\\.tmp\\plugin-architecture-live-run\\workspace\\repo-manual-repo-task-002",
  "last_error": null
}
```

说明：

- local-task 主链路完成到 `awaiting_review`
- 本地 review artifact 已生成
- 分支创建成功
- 工作区隔离成功

### 工件证据

本地 review artifact：

- `.tmp/plugin-architecture-live-run/reviews/pull-requests/local-bc17c8fd.md`

其中明确记录：

- Review ID：`local-bc17c8fd`
- Source Branch：`refs/heads/ai/task-002-add-offline-validation-note`
- task 结果说明、review summary、verification summary

工作区内修改后的 README：

- `.tmp/plugin-architecture-live-run/workspace/repo-manual-repo-task-002/README.md`

内容包含：

- 新增 `## Result`
- 新增 bullet：`- Completed by ClawHarness local-task Docker validation.`

源仓库 README 保持未改：

- `.tmp/plugin-architecture-live-run/repo/README.md`

### RunGraph 与 skill selection 证据

从 `.tmp/plugin-architecture-live-run/harness.sqlite3` 读取到：

- 根 run：`manual-repo-task-002`
- 状态：`awaiting_review`
- 子 run：
  - `agent-planner`
  - `agent-executor`
  - `agent-reviewer`
  - `agent-verifier`
- skill selection key：
  - `task:planner:local-task`
  - `task:executor:local-task`
  - `task:reviewer:local-task`
  - `task:verifier:local-task`

这说明：

- 真实运行经过了多 agent 路径
- local-task provider 下的 canonical skill 选择逻辑被实际消费
- 当前架构收口没有把 RunGraph、skill selection 或本地闭环跑坏

## 文档与 ownership 收口

当前仓库的用户文档已经按新的 ownership 模型收口：

- `README.md`
- `README.zh-CN.md`
- `deploy/README.md`

当前对外约定已经统一为：

- canonical source：`skills/core/`
- compatibility mirror：`openclaw-plugin/skills/`
- projection command：`python -m harness_runtime.skill_projection`
- drift check：`python -m harness_runtime.skill_projection --check`

## 剩余风险

### Windows `codex-cli` 输出解码噪声

这次真实离线运行虽然成功，但在命令退出后仍出现了一条线程级异常：

- `UnicodeDecodeError: 'gbk' codec can't decode ...`

影响判断：

- 本次 run 最终返回码为 `0`
- root run 成功进入 `awaiting_review`
- review artifact 与工作区产物完整生成

因此它当前属于“运行输出解码噪声”，不是阻塞性功能失败；但后续仍建议在 Windows `codex-cli` 路径上，把 subprocess 文本解码策略改成显式 UTF-8 或带容错回退，避免真实运行日志被额外异常污染。

## 最终判定

以 2026-04-09 当前仓库状态来看，这轮“插件化与单一 Skill 真源改造”已经完成闭环：

- 架构边界成立
- 文档边界成立
- 回归验证通过
- 真实离线闭环通过
- 兼容投影校验通过

后续如果继续推进，就不再是这轮架构收口本身，而是下一轮功能增强或 Windows `codex-cli` 输出健壮性修复。
