# ClawHarness v1 验收证据快照

日期：2026-04-05
状态：Azure DevOps + OpenClaw ACP + 本地 Rocket.Chat 下，V1 的任务到 PR 以及 PR 反馈闭环已完成真实验证
配套文档：
- `.omx/plans/test-spec-clawharness-v1-2026-04-05.md`
- `.omx/plans/pdca-clawharness-v1-2026-04-05.md`

## 验证命令

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner harness_runtime rocketchat_notifier run_store tests
python -m harness_runtime.main --task-id 29 --repo-id 06c34683-1500-42ae-a939-e68ef63ef6f6
python -m harness_runtime.main --task-id 30 --repo-id 06c34683-1500-42ae-a939-e68ef63ef6f6
```

额外环境验证：

- `openclaw health`
- `openclaw agents list`
- `openclaw plugins list`

## 结果摘要

- 本地自动化测试：通过，`54/54`
- Python 模块编译检查：通过
- OpenClaw ACP 真实 smoke：通过
- 真实 Azure DevOps 任务 `29` 进入 `awaiting_review` 并创建 PR `17`
- PDCA 第 1 轮发现一个真实问题：执行结果工件被写进克隆仓库并被一起提交
- harness 已修正为把执行器工件写到 `~/.openclaw/workspace/harness/.executor-artifacts/<run_id>/`
- 真实 Azure DevOps 任务 `30` 进入 `awaiting_review` 并创建干净 PR `18`
- 真实 Azure DevOps 任务 `31` 进入 `awaiting_review`，创建 PR `19`，随后在同一 run 上完成了真实 PR 反馈恢复
- PR `18` 只包含 `README.md`
- PR `19` 的评论线程 `79` 中同时存在人工评审评论与 ClawHarness 的回复
- 第 1 轮验证中产生的问题 PR `17` 已在第 2 轮修正验证后废弃
- 审计证据已持久化到 `C:\Users\lus\.openclaw\harness\harness.db`

## PDCA 过程

### 第 0 轮：预检修复

问题：
- Azure Boards 不接受同时传 `fields` 与 `$expand=relations` 的 `get_task` 请求

动作：
- 修正 `harness_runtime/orchestrator.py`，只请求必需字段
- 在 `tests/test_task_orchestrator.py` 中补回归测试

### 第 1 轮：第一次真实端到端运行

工作项：
- id：`29`
- 页面：`https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_workitems/edit/29`

运行：
- run id：`manual-ai-review-test-29`
- 状态：`awaiting_review`

仓库结果：
- 分支：`refs/heads/ai/29-v1-validation-append-harness-note-to-rea`
- commit：`0c8b8a6039648620c25825e8fd3dbf8586dc3eb0`
- PR id：`17`
- 最终状态：`abandoned`

发现的问题：
- `git log --stat` 显示推送的提交中同时包含 `README.md` 与执行结果工件
- 这证明主闭环是通的，但也暴露了运行时工件隔离问题

### 第 2 轮：工件隔离修复后的纠偏重跑

工作项：
- id：`30`
- 页面：`https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_workitems/edit/30`

运行：
- run id：`manual-ai-review-test-30`
- 状态：`awaiting_review`

仓库结果：
- 分支：`refs/heads/ai/30-v1-validation-rerun-readme-note-without-`
- commit：`8411da5ca57b1eb516590982507aea8e1f0d8c2f`
- PR id：`18`
- PR 状态：`active`

工作区与工件证据：
- 工作区：`C:\Users\lus\.openclaw\workspace\harness\AI-Review-Test-manual-ai-review-test-30`
- 执行结果工件：`C:\Users\lus\.openclaw\workspace\harness\.executor-artifacts\manual-ai-review-test-30\executor-result.json`
- 任务评论数：`1`

内容证据：
- 执行结果摘要：`Appended a V1 Harness Validation section to README.md and verified README.md is the only modified file.`
- `git log -1 --stat` 显示只有 `README.md` 一个变更文件

### 第 3 轮：修正 ACP 恢复兼容性后的真实 PR 反馈恢复

工作项：
- id：`31`
- 页面：`https://dev.azure.com/lusipad/ba6a3017-b334-48c5-ac75-2696bac2cf94/_workitems/edit/31`

运行：
- run id：`manual-ai-review-test-31`
- 最终状态：`awaiting_review`
- run 记录中的会话标识：`agent:codex:acp:ebe3c03a-2979-49c4-b6a7-2b2c99f8b699`
- PR id：`19`

真实反馈证据：
- 在 PR `19` 上创建了真实评论线程 `79`
- 评论内容要求在 `Build and Test` 下增加一条 README 说明
- ClawHarness 成功解析 `pr_id -> run_id`，回到同一 `manual-ai-review-test-31`
- 审计链显示：`pr_feedback_queued -> pr_feedback_loaded -> pr_feedback_executor_completed -> checks_completed -> pr_feedback_replied -> awaiting_review`

仓库证据：
- 分支：`refs/heads/ai/31-live-ac-06-validation-readme-follow-up-v`
- 同步后的 commit：`fe1d7135bbca37f88176056148411191b37e7e15`
- 工作区 README 新增内容：

```md
Recheck any README updates after review feedback to confirm the documented build and test steps still match the latest branch state.
```

兼容性结论：
- 真实验证表明：当前 gateway 配置下，已结束的 ACP 底层执行资源不能被直接重新 resume
- harness 已调整为：保留逻辑上的 `run_id/session_id`，但在同一 run、工作区和分支上下文中启动新的 ACP 执行来完成恢复

## 验收映射

### AC-01：单任务认领与去重

状态：
- 本地通过

证据：
- `tests/test_run_store.py::test_claim_run_accepts_first_request`
- `tests/test_run_store.py::test_claim_run_rejects_duplicate_event_fingerprint`
- `tests/test_run_store.py::test_claim_run_rejects_second_active_run_for_same_task`

### AC-02：结构化规划输出

状态：
- 本地通过，并已在真实运行中使用

证据：
- `tests/test_codex_acp_runner.py::test_build_task_prompt_renders_constraints_and_artifacts`
- `codex_acp_runner/runner.py` 中的任务提示生成逻辑
- 真实任务 `29`、`30`、`31` 都通过 ACP 完成并产出结构化结果工件

### AC-03：Codex ACP 编码执行

状态：
- 真实环境通过

证据：
- `tests/test_codex_acp_runner.py::test_build_spawn_payload_uses_acp_runtime`
- `tests/test_openclaw_client.py::test_invoke_tool_posts_to_tools_invoke_endpoint`
- 真实运行 `manual-ai-review-test-30`

### AC-04：PR 前检查门禁

状态：
- 真实环境通过，当前以最小仓库画像验证

证据：
- `manual-ai-review-test-30` 在推送和开 PR 前记录了 `checks_completed`
- `harness_runtime/orchestrator.py` 中的门禁实现

### AC-05：分支推送与 PR 创建

状态：
- 真实环境通过

证据：
- 真实任务 `30` 推送了分支 `refs/heads/ai/30-v1-validation-rerun-readme-note-without-`
- 真实任务 `30` 打开 PR `18`
- `tests/test_ado_client.py::test_create_pull_request_builds_expected_payload`

### AC-06：PR 反馈恢复

状态：
- 真实环境通过

证据：
- `tests/test_harness_runtime.py::test_pr_event_queues_existing_run_into_runtime_orchestrator`
- `tests/test_task_orchestrator.py::test_resume_from_pr_feedback_reuses_session_and_replies_without_new_run`
- `tests/test_run_store.py::test_update_run_fields_and_lookup_by_pr_and_ci`
- 真实运行 `manual-ai-review-test-31` 从 PR `19` 恢复
- 真实线程 `79` 中存在人工评论与 ClawHarness 回复
- live 审计记录证明 `run_id` 未变，并回到了 `awaiting_review`

### AC-07：CI 失败恢复

状态：
- 本地通过，真实环境验证受目标项目缺少 CI build 阻塞

证据：
- `tests/test_harness_runtime.py::test_ci_event_queues_existing_run_into_runtime_orchestrator_and_notifies`
- `tests/test_task_orchestrator.py::test_resume_from_ci_failure_retries_build_and_updates_run`
- `tests/test_task_orchestrator.py::test_resume_from_ci_failure_escalates_when_executor_requires_human`
- `tests/test_ado_client.py::test_retry_build_queues_new_build_from_existing_metadata`

阻塞事实：
- `2026-04-05` 在 `AI-Review-Test` 上执行 `list_builds(top=10)` 返回空列表，当前没有可用于真实 `ci.run.failed` 恢复验证的 build definition / build run

### AC-08：Rocket.Chat 生命周期通知

状态：
- 本地通过，Windows 真实环境通过

证据：
- `tests/test_rocketchat_notifier.py`
- `rocketchat_notifier/notifier.py`
- 本地 Rocket.Chat 工作区启动在 `http://127.0.0.1:3000`

### AC-09：Docker 部署支持

状态：
- 资产已完成，真实环境验证待补

证据：
- `deploy/docker/compose.yml`
- `deploy/docker/harness-bridge.Dockerfile`
- `deploy/docker/.env.example`

### AC-10：原生部署支持

状态：
- Windows 真实验证完成；Linux service-manager 真实验证待补

证据：
- `deploy/systemd/openclaw.service`
- `deploy/systemd/harness-bridge.service`
- `deploy/windows/install-openclaw.ps1`
- `deploy/windows/install-rocketchat-local.ps1`
- `deploy/windows/run-harness.ps1`

### AC-11：工作流稳定性规则

状态：
- 本地通过

证据：
- flow 草稿使用统一能力名
- 静态搜索未发现直接供应商专用调用污染 flow 契约

### AC-12：安全与策略护栏

状态：
- 部分完成

证据：
- `deploy/config/harness-policy.yaml`
- Windows 用户级环境变量密钥注入已真实验证

### AC-13：可观测性与审计

状态：
- 运行时审计已真实通过，运维遥测仍部分完成

证据：
- `C:\Users\lus\.openclaw\harness\harness.db`
- `manual-ai-review-test-29`、`30`、`31` 的真实审计链
- `deploy/scripts/` 中的健康检查脚本

## 剩余风险

- 真实 CI 恢复仍受目标 Azure DevOps 项目没有构建资源阻塞
- Docker 与 Linux 原生服务资产已具备，但仍需目标环境启动验证
- 受保护分支、reviewer 和 CI policy 更严格的仓库可能还需要小幅适配
- V1 已证明任务到 PR 以及 PR 反馈修复闭环，但 CI 故障后的 patch / retry 真实闭环仍待环境条件满足后验证
