---
name: implement-task
description: 将批准后的任务计划转换为 ACP 编码请求，并收集执行结果。
---

# implement-task

## 用途

使用 `analyze-task` 的输出、仓库策略和工作区路径，通过 ACP 驱动 Codex 执行实现。

## 输入

- `analyze-task` 的计划输出
- workspace path
- repository policies

## 必要输出

- 代码改动
- 测试或检查摘要
- 提交摘要

## 约束

- 禁止直接合并
- 禁止直接推送受保护分支
- 在创建 PR 之前必须先跑检查
