# `implement-task`

状态：草案契约

## 用途

把 `analyze-task` 的输出转成 ACP 编码请求，并收集执行结果。

## 输入

- `analyze-task` 的计划输出
- workspace path
- repository policies

## 必要输出

- 代码改动
- 测试或检查摘要
- 提交摘要

## 验收说明

- 必须保留“不直接合并”和“禁止推送受保护分支”的规则。
- 必须输出足够信息，让 PR 流程和恢复流程无需重新分析即可继续。
