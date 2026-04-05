# Azure DevOps 请求清单

状态：MVP 基线草案
模式：`ado-rest`

本文档定义 Azure DevOps 适配器在 MVP 阶段暴露的请求面。所有共享 flow 都必须映射到统一能力名，供应商特定的 URL 路径只允许留在 `ado_client` 内部。

实现说明：
- 首版 `ado_client` 基于 Python 标准库实现，不引入第三方 HTTP 依赖。
- 下列接口形状已对照 `2026-04-05` 检查过的 Microsoft Learn Azure DevOps REST 文档。
- 工作项评论当前仍需使用预览版本 `7.0-preview.3`，其余工作项、Git PR、构建接口使用 `7.1`。

## 任务能力

### `task.list_candidates`

用途：
- 在开启轮询模式时发现可执行工作项

期望输入：
- project
- query 或队列过滤条件
- 如有需要，分页游标

期望输出：
- 归一化后的任务摘要列表

### `task.get`

用途：
- 读取 `analyze-task` 所需的任务正文与元数据

期望输入：
- task id
- project

期望输出：
- 含标题、描述、仓库绑定、负责人、标签和修订信息的归一化任务载荷

参考接口：
- `GET /{project}/_apis/wit/workitems/{id}?api-version=7.1`

### `task.update_status`

用途：
- 将 planning、blocked、PR 已创建、completed 等状态回写到 Azure DevOps

期望输入：
- task id
- 状态值或状态迁移
- 可选附加元数据，例如 run id 或 PR url

期望输出：
- 更新后的任务状态

参考接口：
- `PATCH /{project}/_apis/wit/workitems/{id}?api-version=7.1`

### `task.add_comment`

用途：
- 向工作项补充运行摘要、阻塞原因或完成说明

期望输入：
- task id
- Markdown 或纯文本正文

期望输出：
- 新建评论的元数据

参考接口：
- `POST /{project}/_apis/wit/workItems/{id}/comments?api-version=7.0-preview.3`

## 仓库与版本控制能力

### `repo.prepare_workspace`

用途：
- 解析仓库元数据，并为每次运行准备干净的独立工作区

期望输入：
- repo id
- run id
- workspace root
- branch prefix

期望输出：
- workspace path
- default branch
- repo metadata

### `vcs.create_branch`

用途：
- 创建任务级工作分支

期望输入：
- repo id
- base branch
- branch name

期望输出：
- 创建后的分支 ref

### `vcs.commit_and_push`

用途：
- 暂存修改、创建提交并推送工作分支

期望输入：
- workspace path
- branch name
- commit message

期望输出：
- 推送后的 commit sha
- 远端分支 url 或 ref

## Pull Request 能力

### `pr.create`

用途：
- 从任务分支创建初始 PR

期望输入：
- repo id
- source branch
- target branch
- title
- description

期望输出：
- PR id
- PR url
- 如可获取，则返回 reviewer 摘要

参考接口：
- `POST /{project}/_apis/git/repositories/{repositoryId}/pullrequests?api-version=7.1`

### `pr.get`

用途：
- 获取当前 PR 状态

期望输入：
- repo id
- PR id

期望输出：
- 归一化 PR 摘要

参考接口：
- `GET /{project}/_apis/git/repositories/{repositoryId}/pullrequests/{pullRequestId}?api-version=7.1`

### `pr.list_comments`

用途：
- 为恢复闭环收集未解决的评审反馈

期望输入：
- repo id
- PR id

期望输出：
- 含状态与作者信息的归一化评论列表

参考接口：
- `GET /{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/threads?api-version=7.1`

### `pr.reply`

用途：
- 在处理完评审反馈后回帖

期望输入：
- repo id
- PR id
- body

期望输出：
- 新建回复的元数据

参考接口：
- `POST /{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/threads/{threadId}/comments?api-version=7.1`

## CI 能力

### `ci.get_status`

用途：
- 读取当前 PR 或运行对应的校验状态

期望输入：
- repo id
- PR id 或 CI run id

期望输出：
- 归一化 CI 状态摘要

参考接口：
- `GET /{project}/_apis/build/builds/{buildId}?api-version=7.1`

### `ci.retry`

用途：
- 在策略允许时重新触发失败的校验链路

期望输入：
- repo id
- CI run id

期望输出：
- 重试请求确认结果

参考接口：
- `POST /{project}/_apis/build/builds?api-version=7.1`

实现说明：
- Azure DevOps 并没有像其他接口那样，统一暴露“按原样重试这个失败运行”的通用端点。
- 当前 MVP 基线实现会读取原构建的 `definition.id`、`sourceBranch`、`sourceVersion` 和 `parameters`，然后重新排队一个构建。
- 这是面向 MVP 的务实推断，正式上线前仍需在目标 CI 配置中验证。

## 归一化事件契约

所有 Azure DevOps 入站事件在进入 flow 之前都应先被归一化：

```json
{
  "event_type": "task.created",
  "provider": "azure-devops",
  "source_id": "evt-123",
  "task_id": "12345",
  "task_key": "AB#12345",
  "repo_id": "repo-1",
  "pr_id": null,
  "ci_run_id": null,
  "chat_thread_id": null,
  "actor": {
    "id": "user-1",
    "name": "alice"
  },
  "payload": {}
}
```

## 待确认问题

- Azure DevOps Services 与 Azure DevOps Server 在 REST 端点和载荷上是否有关键差异。
- 分支策略或构建状态 API 是否差异大到需要适配器分叉。
- 目标 CI 配置下的真实重试语义是否与当前基线一致。
