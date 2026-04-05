# ClawHarness v1 PDCA 执行记录

日期：2026-04-05
状态：V1 主闭环已完成到真实 PR 反馈；CI 与部署扩展验证仍在后续周期中
配套文档：
- `.omx/plans/prd-clawharness-v1-2026-04-05.md`
- `.omx/plans/test-spec-clawharness-v1-2026-04-05.md`

## 目标

用短周期 PDCA 驱动 ClawHarness MVP，让每个实现增量都具备清晰范围、验证证据和纠偏记录。

## 工作规则

- 每个周期只负责一个边界清晰的里程碑，或一个高风险跨模块问题
- 周期开始前必须绑定明确的验收标准
- 周期结束前必须沉淀证据与剩余风险
- 可恢复问题不算完成，必须继续进入纠偏回路

## 标准 PDCA 模板

### Plan

必须产出：
- 周期目标
- 涉及文件或模块
- 对应测试规范中的 AC
- 风险、假设和进入条件
- 预期证据

### Do

必须执行：
- 仅实现本轮范围内内容
- 记录改动文件与关键设计决策
- 同步记录已执行的验证命令

### Check

必须产出：
- 每条目标 AC 的通过/失败结论
- 证据路径
- 缺陷列表
- 预期与实际差异

### Act

必须产出：
- 保留、修复、缩小或扩展范围的决策
- 待办与下轮入口条件

## 初始周期图

### 周期 0：基线与骨架

目标 AC：
- AC-11
- AC-12（部分）

### 周期 1：运行时核心

目标 AC：
- AC-01
- AC-13（部分）

### 周期 2：Azure DevOps Provider 基线

目标 AC：
- AC-05（部分）
- AC-11

### 周期 3：ACP 执行器与主流程

目标 AC：
- AC-02
- AC-03
- AC-04
- AC-05

### 周期 4：恢复闭环

目标 AC：
- AC-06
- AC-07

### 周期 5：通知与部署

目标 AC：
- AC-08
- AC-09
- AC-10
- AC-12（部分）
- AC-13（部分）

### 周期 6：加固与发布门禁

目标 AC：
- AC-01 到 AC-13 全量收口

## 当前基线

当前仓库已经具备以下基础：

- `run_store` 可执行
- `ado_client` 可执行
- `codex_acp_runner` 可执行
- `harness_runtime` 可执行
- `rocketchat_notifier` 可执行
- OpenClaw 插件骨架、flows、skills 已落地
- 部署资产已提供

当前验证证据包括：

- `python -m unittest discover -s tests -v`：`54/54`
- `python -m compileall ado_client codex_acp_runner harness_runtime rocketchat_notifier run_store tests`
- `python -m harness_runtime.main --help`
- OpenClaw ACP 真实 smoke
- 真实 Azure DevOps 任务 `29` 到 PR `17`
- 真实 Azure DevOps 任务 `30` 到干净 PR `18`
- 真实 Azure DevOps 任务 `31` 到 PR `19`，再到同一 run 的 PR 反馈恢复

## 周期 3 纠偏状态

目标：
- 用真实 Azure DevOps 项目验证 V1 主 happy path

计划范围：
- `ado_client`
- `codex_acp_runner`
- `harness_runtime`
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`

验收结果：
- AC-02：通过
- AC-03：真实环境通过
- AC-04：真实环境通过（最小仓库画像）
- AC-05：真实环境通过

证据：
- 第 1 轮 live run：工作项 `29`，PR `17`
- 第 2 轮 live run：工作项 `30`，PR `18`
- 自动化测试：`54/54`

剩余风险：
- 在周期 3 结束时，AC-06 与 AC-07 仍未完成真实验证
- Docker 和 Linux 部署仍待验证

动作决策：
- 关闭主 happy path
- 将下一轮集中到恢复路径、部署与策略联动

## 周期 4 纠偏状态

目标：
- 关闭真实 PR 反馈恢复闭环，并修正 ACP 恢复兼容性问题

计划范围：
- `harness_runtime/orchestrator.py`
- `harness_runtime/bridge.py`
- `run_store/store.py`
- `tests/test_harness_runtime.py`
- `tests/test_task_orchestrator.py`
- `tests/test_run_store.py`
- `.omx/plans/evidence-clawharness-v1-2026-04-05.md`
- `.omx/plans/pdca-clawharness-v1-2026-04-05.md`

验收结果：
- AC-06：真实环境通过
- AC-07：本地通过，真实环境因缺少 build 资源被阻塞

证据：
- live task `31` 打开 PR `19`
- PR `19` 上创建真实评论线程 `79`
- `manual-ai-review-test-31` 在同一 `run_id` 上处理评论并回到 `awaiting_review`
- 自动化测试：`54/54`
- `compileall`：通过

关键发现：
- 已结束的 ACP 底层资源不能在当前 gateway 配置中直接 resume
- gateway 对恢复执行存在 `thread=true`、重复 `label` 和已结束资源重开等兼容限制

修正动作：
- 恢复链路不再强依赖“重开已结束 ACP 资源”
- 保留同一 `run_id`、`workspace_path`、`branch_name` 和逻辑 `session_id`
- 在同一运行上下文中启动新的 ACP 执行完成恢复
- 明确把 commit / push / PR reply / CI retry 的发布动作收回到 harness 侧

剩余风险：
- 当前验证项目没有 build definitions / build runs，无法完成 AC-07 live 闭环
- Docker 和 Linux 部署仍待真实环境验证
- 受保护分支、reviewer 和 CI policy 更严格的仓库仍需验证

动作决策：
- 将 V1 协作闭环视为已完成到 PR 反馈层
- 下一纠偏周期聚焦于具备真实构建定义的项目，用于完成 AC-07 live 验收
