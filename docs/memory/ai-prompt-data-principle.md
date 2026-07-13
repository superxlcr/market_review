---
name: ai-prompt-data-principle
description: AI prompt 数据原则 — 只提供数据和用法说明，不下结论
metadata: 
  node_type: memory
  type: project
  tags: 
    - ai
    - prompt
    - design
  originSessionId: c0278b9a-15e8-4e5c-b6a1-fc07f2c75e7c
---

## AI Prompt 数据原则

**核心：我们给数据和用法说明，AI 下结论。**

### Prompt 输入只能有两类

1. **原始/加工后的数据本身** — 数字、列表、时间序列
   - ✅ `{"日期": "06-03", "成交额": "22000亿", "涨跌": "跌多"}`
   - ❌ `"近3日放量明显，前7日量能偏低"` （这是结论）

2. **其他 AI 已生成的导语/总结** — 用于进一步提炼
   - ✅ summary prompt 吃 guide_breadth + guide_sh + guide_cz

### 给 AI 的数据要求

- 多天数据用列表，让 AI 自己找规律
- 不预判趋势方向、不写"情绪降温"、"下降收窄"等结论性文字
- 自定义指标（如 3浪3）要附说明+用法，但用法只讲"怎么看"，不讲"现在是什么"

### Prompt 模板结构

```
1. 角色设定
2. 分析框架/优先级（严格按顺序）
3. 指标用法说明（仅对自定义指标）
4. 输出格式要求
5. 数据
```

### Related
- [[ai-guide-design]]
