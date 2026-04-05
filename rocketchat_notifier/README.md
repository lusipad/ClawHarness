# `rocketchat_notifier`

状态：基础实现已完成

用途：
- 通过 webhook 向 Rocket.Chat 发送生命周期通知

MVP 事件：
- 任务开始
- PR 已创建
- CI 失败
- 任务被阻塞
- 任务完成

当前实现：
- Python 标准库版本通知器位于 `rocketchat_notifier/notifier.py`
- 生命周期消息使用 Rocket.Chat incoming webhook 消息结构
- 测试已覆盖消息格式化和 HTTP 失败处理

后续关注点：
- 丰富 webhook 模板
- 将投递成功与失败写入运行时审计链路
