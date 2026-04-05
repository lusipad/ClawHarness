---
name: gateway-startup
description: 在 ClawHarness 插件 hooks 被加载时输出一条启动日志。
metadata:
  openclaw:
    events:
      - gateway:startup
---

# gateway-startup

输出一条简短的启动标记，便于运维确认 harness hook 包已成功加载。
