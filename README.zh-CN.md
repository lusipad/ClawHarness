# ClawHarness

[English](README.md) | 简体中文

ClawHarness 是一个面向 Azure DevOps 仓库的自主化任务到 PR 执行闭环。它把 Azure DevOps 工作项、OpenClaw ACP 执行、仓库本地校验、分支与 PR 自动化，以及可选的 Rocket.Chat 生命周期通知串成一条可重复的交付链路。

## 功能概览

- 使用基于 SQLite 的运行时存储完成任务认领、去重、加锁和审计
- 为每次任务运行准备隔离工作区，并创建任务分支
- 通过 OpenClaw ACP 调用 Codex 完成实现工作
- 在提交和推送前执行本地检查
- 自动创建 PR，并为每次运行保留审计记录
- 支持通过 webhook 继续处理 PR 反馈和 CI 故障恢复
- 提供 Windows、Linux systemd 和 Docker 部署资产

## 仓库结构

- `ado_client/`：Azure DevOps REST 客户端，负责工作项、仓库、PR 和构建操作
- `codex_acp_runner/`：ACP 执行器封装与结构化结果处理
- `harness_runtime/`：Bridge 服务、编排逻辑与运行时配置加载
- `rocketchat_notifier/`：Rocket.Chat webhook 通知器
- `run_store/`：SQLite schema 与运行态持久化原语
- `openclaw-plugin/`：OpenClaw 插件入口、hooks、flows 与 skills
- `deploy/`：Docker、systemd、Windows 以及配置模板
- `.omx/plans/`：PRD、测试规范、PDCA 记录与验收证据

## 当前 V1 状态

- V1 主 happy path 已在 Azure DevOps 和 OpenClaw ACP 上完成真实环境验证
- 任务到分支到 PR 的真实闭环已完成
- PR 反馈恢复链路也已经完成真实环境验证
- 证据与 PDCA 记录保存在 `.omx/plans/`

## 快速开始

1. 配置必需环境变量，例如 `ADO_BASE_URL`、`ADO_PROJECT`、`ADO_PAT`、`OPENCLAW_HOOKS_TOKEN`、`OPENCLAW_GATEWAY_TOKEN`。
2. 阅读 `deploy/README.md` 选择部署方式。
3. 按目标环境运行 Windows 安装脚本，或者使用 Docker / systemd 资产。
4. 运行自动化检查：

```sh
python -m unittest discover -s tests -v
python -m compileall ado_client codex_acp_runner harness_runtime rocketchat_notifier run_store tests
```

5. 手工触发一次任务运行：

```sh
python -m harness_runtime.main --task-id <work-item-id> --repo-id <repo-id>
```

## 验证说明

当前实现已经最稳定地覆盖以下 V1 主链路：

- 任务认领与去重
- ACP 执行
- 本地检查门禁
- 分支推送
- PR 创建
- PR 反馈后的同一运行闭环续跑

当前仍需要补齐更广泛真实环境验证的部分主要是：

- 真实 CI 失败后的恢复与重试
- 受保护分支和评审策略更严格的仓库策略联动
- Docker / Linux 原生部署的更广覆盖验证
