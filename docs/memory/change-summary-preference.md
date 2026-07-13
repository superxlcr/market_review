---
name: change-summary-preference
description: User prefers a summary table after each round of code changes
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d164b60f-9366-4e2d-a074-900bd0d24c3e
---

每次代码改动完成后，用表格形式做「本轮改动汇总」，列出每个文件和做了什么。

格式示例：
| 文件 | 做了什么 |
|------|---------|
| [file.py:10-20](path/file.py#L10-L20) | 具体改动描述 |

**Why:** 用户喜欢这种清晰的汇总方式，方便快速了解改动范围。
**How to apply:** 每次改完代码后，自动附上汇总表。
