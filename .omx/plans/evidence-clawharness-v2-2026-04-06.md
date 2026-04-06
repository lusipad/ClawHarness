# ClawHarness V2 验收证据快照

日期：2026-04-06
状态：V2 Core 代码、运行态 API、bot-view sidecar、Azure DevOps task -> PR -> PR feedback -> CI recovery 闭环均已完成真实验证；GitHub provider 真实联调仍缺少 `GITHUB_TOKEN`

配套文档：
- `.omx/plans/prd-clawharness-v2-2026-04-05.md`
- `.omx/plans/test-spec-clawharness-v2-2026-04-05.md`

## 本地验证

- `python -m unittest discover -s tests -v`
  - 结果：通过，`120/120`
- `python -m compileall ado_client codex_acp_runner github_client harness_runtime rocketchat_notifier run_store workflow_provider tests`
  - 结果：通过
- 本轮 Azure 修复相关回归：
  - `python -m unittest tests.test_ado_client tests.test_task_orchestrator -v`
  - `python -m unittest tests.test_ado_client -v`
  - `python -m compileall ado_client tests`
  - 结果：通过

## 真实环境结果摘要

- Docker 栈正常：
  - `openclaw-gateway`
  - `clawharness-bridge`
  - `openclaw-bot-view`
- Azure DevOps 真实 work item -> branch -> PR：通过
- Azure PR feedback 恢复：通过
- Azure CI recovery：通过
- Windows self-hosted Azure agent 环境修复：通过

## 关键真实链路

### 1. task -> PR

工作项：
- id：`45`
- 标题：`V2 full live validation: task to PR to CI recovery to successful rerun`

根 run：
- run id：`manual-ai-review-test-45`
- 状态：`awaiting_review`
- 分支：`refs/heads/ai/45-v2-full-live-validation-task-to-pr-to-ci`
- PR：`27`

PR 结果：
- 标题：`AI-Review-Test#45: V2 full live validation: task to PR to CI recovery to successful rerun`
- source branch 初始提交：`d02a390aa9060ef12970694b001b508d97b47669`

行为证据：
- planner / executor / reviewer / verifier 子 run 均已真实执行
- 初始 PR 只修改 `README.md`
- README 初始版本故意不包含精确 marker：
  - `CI recovery marker: README verified for pipeline reruns.`

### 2. PR feedback

已完成的真实反馈恢复链路：
- 根 run：`manual-ai-review-test-38`
- PR：`22`
- 子 run：`manual-ai-review-test-38--pr-feedback--775074ec`
- Azure thread：`81`

结论：
- ClawHarness 已在真实 Azure PR 评论线程中完成读取评论、恢复执行、提交修复与回帖

### 3. CI recovery

初始失败 build：
- build：`42`
- branch：`refs/heads/ai/45-v2-full-live-validation-task-to-pr-to-ci`
- 结果：`failed`

失败证据：
- 失败步骤：`Validate README CI recovery marker`
- 控制台关键输出：`README is missing the CI recovery marker.`

bridge 事件投递：
- `POST http://127.0.0.1:8080/webhooks/azure-devops`
- header：`x-ado-event-type: ci.run.failed`
- bridge 返回：`accepted: true`

恢复子 run：
- run id：`manual-ai-review-test-45--ci-recovery--f7ccbe33`
- relation：`ci-recovery`
- previous build：`42`
- retry build：`43`
- 状态：`completed`

恢复动作证据：
- 子 run 结论：构建失败仅因 README 缺少精确 marker，可安全自动修复
- 子 run 已将 marker 写入 `README.md`
- 子 run 本地检查通过：
  - `README marker presence`
  - `git diff --check`

自动重试 build：
- build：`43`
- queue：`Default` / queue id `38`
- source branch：`refs/heads/ai/45-v2-full-live-validation-task-to-pr-to-ci`
- source version：`0a15306ea4b581114f98160f26e2097e86774674`
- 结果：`succeeded`

成功证据：
- 成功步骤：`Validate README CI recovery marker`
- 控制台显示已检查 marker 且无报错
- 根 run `manual-ai-review-test-45` 已同步记录：
  - `ci_run_id = 43`
  - 父子 run graph 已包含 `ci-recovery` 子链路

## Windows self-hosted agent 修复证据

问题现象：
- 旧 agent 进程下，PowerShell task 在 build `40` 中报错：
  - `The following error occurred while loading the extended type data file`
  - `ConvertTo-SecureString ... module could not be loaded`

修复动作：
- 停止旧的 `Agent.Listener.exe`
- 从干净的 `cmd.exe` 重新启动 agent
- 显式收敛环境变量：
  - `PSModulePath=C:\Program Files\WindowsPowerShell\Modules;C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules`
  - 清空 `POWERSHELL_DISTRIBUTION_CHANNEL`
  - 保留 `POWERSHELL_TELEMETRY_OPTOUT=1`

修复验证：
- 同分支人工重排 build：`41`
- 结果：`succeeded`
- 说明 self-hosted Windows agent 环境问题已解除，后续 CI recovery 自动重试才得以在 build `43` 上真实跑通

## 结论

V2 当前已完成的真实闭环：
- Docker 本地部署
- OpenClaw gateway + ClawHarness bridge + bot-view sidecar
- Azure DevOps work item -> 多 agent task run -> branch -> PR
- Azure PR feedback 恢复
- Azure CI failure -> webhook -> 自动恢复子 run -> 自动重试 -> 成功 build

仍未完成的真实外部联调：
- GitHub provider live
  - 原因：当前环境未提供 `GITHUB_TOKEN`
