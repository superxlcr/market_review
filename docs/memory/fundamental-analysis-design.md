---
name: fundamental-analysis-design
description: 基本面分析功能设计讨论 — 产业链知识库方案探索
metadata: 
  node_type: memory
  type: project
  tags: 
    - fundamental-analysis
    - industry-chain
    - brainstorming
  originSessionId: b646c0cd-98cc-4a0e-96b8-7f9438559754
---

# 基本面分析 — 产业链功能设计讨论

**状态：** 进行中（2026-07-05 暂停，明天继续）

## 背景

用户已完成技术分析体系，想扩展基本面分析。核心诉求：
- **个股基本面快速了解**：输入标的 → 了解公司做什么 + 在产业链什么位置
- **产业链上下游认知**：理解整个产业链结构，上下游互相印证
- **数据代码写死，AI 只做解读**：延续「代码做计算、AI 做推理」的核心理念

## 关键发现

### tushare 能提供的

1. **`ths_index` + `ths_member`**：同花顺 409 个概念板块，可按概念查成分股、按股票反查所属概念
2. **`stock_company`**：`main_business`（主要业务）、`introduction`（公司介绍）、`business_scope`（经营范围）
3. **`index_classify` + `index_member_all`**：申万行业分类（已在使用）

### tushare 的局限

**同花顺概念板块不是按「产业链分类体系」组织的。** 例如半导体相关只有 ~10 个概念板块：
- 芯片概念、MCU芯片、存储芯片、汽车芯片、第三代半导体、先进封装、光刻机、光刻胶、国家大基金持股、中芯国际概念

**缺少独立的：** 芯片设计、半导体设备、半导体材料、晶圆制造、EDA、IP核、FPGA、模拟芯片、功率半导体、IGBT 等大类概念板块。

### 结论

光靠 tushare 概念板块，做不到「输入股票 → 知道在产业链的设计/设备/材料/封测哪个位置」。需要用户自建分类体系。

## 讨论到的解决方案（待明天确定）

- **A. 申万行业映射**：将相关申万三级行业手工归入用户定义的产业链大类
- **B. 概念板块关键字归类**：把 409 个概念中半导体相关的挑出来，手工归入大类
- **C. 纯 YAML 维护**：用户自己定义产业链结构 + 标的，不依赖 tushare 自动推断

## 下一步

1. 用户确认产业链分类体系的建设方案（A/B/C 或混合）
2. 选择一个具体产业链试点（如半导体）
3. 设计 YAML 知识库格式 + tushare 数据联动方案
4. 确定 Dashboard 页面形态

## 相关 memory
- [[market-panorama-reference]]
- [[database-schema-reference]]
- [[data-layer-architecture]]
- [[ai-prompt-data-principle]]
