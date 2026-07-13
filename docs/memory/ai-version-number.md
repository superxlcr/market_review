---
name: ai-version-number
description: AI 功能版本号 X.Y.Z 规则，用于验证热更是否生效
metadata: 
  node_type: memory
  type: project
  originSessionId: c0278b9a-15e8-4e5c-b6a1-fc07f2c75e7c
---

DashboardService._AI_VERSION = "X.Y.Z"，用于每次重启后验证代码是否热更成功。

规则（`dashboard/services/dashboard_service.py` 注释也有一份）：
- **X** — 大板块上线 +1，Y/Z 归零。当前 1 = 市场全景。后续：2 = 个股追踪，3 = 板块分析...
- **Y** — 大板块内新增子版块 +1，Z 归零。例如：加了市场概览导语、指数导语、每日总结等。
- **Z** — 每次本地改完代码、想验证重启是否生效时 +1。就是验证计数器。

勿随意改 X 或 Y 的语义，Z 可以频繁动。
