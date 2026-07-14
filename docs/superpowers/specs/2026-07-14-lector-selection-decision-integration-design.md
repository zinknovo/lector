# Lector 选品决策整合设计

## 1. 目标与边界

将当前独立的选品工具整合为由 ReAct Agent 自由编排的三阶段能力，并用统一决策模型收口利润、物流、市场表现与供应商风险。

本次修改主提示词、决策工具、报告工具、Demo 与测试。不修改 FastAPI、server、middleware 等框架代码，不新增固定 LangGraph 流水线。

## 2. 架构

```text
ReAct Agent
  ├─ market_trend_research
  ├─ item_search / product_scraper
  ├─ price_compare / shipping_calc
  ├─ profit_calculator
  ├─ supplier_evaluator
  └─ selection_decision
          ↓
    SelectionDecision[]
          ↓
    shopping_summary
```

- ReAct Agent 根据用户意图自由决定工具调用顺序。
- `selection_decision` 不调用其他工具，只消费既有工具输出、校验字段、计算综合分。
- `shopping_summary` 不计算业务指标，只将 `SelectionDecision[]` 转换为结构化报告和自然语言结论。
- 所有金额、利润和风险数字必须来自工具输出；字段缺失时写入 `missing_data`，不得由 LLM 补全。

## 3. 统一决策模型

`SelectionDecision` 包含：

- 商品身份：product_id、title、platform。
- 市场指标：rating、review_count、sales。
- 财务指标：selling_price_cny、landed_cost_cny、total_cost_cny、net_profit_cny、profit_margin、roi。
- 供应商指标：supplier_risk_score、supplier_risk_level。
- 评分：market_score、profit_score、logistics_score、supplier_score、overall_score、confidence。
- 结论：recommendation、reasons、risks、missing_data。

## 4. 评分与判定

| 维度 | 权重 | 输入 |
|---|---:|---|
| 市场与商品表现 | 30% | rating、review_count、sales |
| 利润能力 | 35% | profit_margin、ROI、net_profit_cny |
| 物流与成本 | 20% | landed_cost_cny、eta_days |
| 供应商风险 | 15% | 1 - supplier_risk_score |

- 每个维度按可用字段计算 0-1 分。
- 缺失整个维度时不按 0 分处理；综合分按已获得维度的权重重新归一化。
- `confidence = 已获得维度权重 / 1.0`。
- `recommend`：overall_score >= 0.70、confidence >= 0.80 且供应商不是 high。
- `watch`：overall_score >= 0.45，或 confidence < 0.80。
- `reject`：overall_score < 0.45，或供应商风险为 high。

## 5. Agent 调用协议

主提示词使用 Lector 品牌，并按意图选择路径：

```text
discover
  market_trend_research → 潜力品类

filter
  item_search/product_scraper
  → price_compare
  → shipping_calc
  → item_picker

full_chain
  完成 filter
  → profit_calculator（每个入选 SKU）
  → supplier_evaluator（每个入选 SKU）
  → selection_decision（每个 SKU）
  → shopping_summary（终结）
```

- full_chain 缺少利润或供应商结果时，不得产生 recommend。
- 子 Agent 可以处理独立 SKU 或品类，但不得调用 `shopping_summary`。
- 长期记忆使用目标市场、利润要求、风险偏好等选品语义。

## 6. 报告

`shopping_summary` 输入为 `SelectionDecision[]`，输出包含：

- `final_text`：LLM 生成的自然语言报告。
- `decisions`：原始统一决策对象。
- `report`：结构化报告行，不丢失利润、风险、置信度和缺失数据。
- `learned_preferences`：选品偏好。

传给 LLM 的 JSON 已包含明确的缺失字段，提示词禁止生成输入中不存在的数值。LLM 不可用时，由调用方保留结构化决策结果。

## 7. 错误处理

- 外部数据失败：仍可构建决策，但记录 missing_data 并降低 confidence。
- 财务数据不完整：profit_score 为空，不能 recommend。
- 供应商风险缺失：supplier_score 为空，不能 recommend。
- 供应商 high：无论其他分数如何均 reject。
- 空决策列表：shopping_summary 返回可解释的空报告，不虚构商品。

## 8. 测试与验收

- 评分维度、权重和缺失数据归一化有单元测试。
- 高供应商风险强制 reject。
- 低置信度不能 recommend。
- shopping_summary 不丢失结构化财务和风险字段。
- 主提示词包含三阶段协议、新工具和 Lector 品牌。
- Demo 输出完整 SelectionDecision。
- 后端 pytest、前端 vitest 和 Demo 全部通过。
