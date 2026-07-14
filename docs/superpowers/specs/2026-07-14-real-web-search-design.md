# Lector 真实搜索与统一汇率设计

## 目标

把本地占位 `web_search` 替换为 Lector 自有的真实搜索边界，并让趋势、实时汇率和比价使用一致的数据链路。

## 搜索接口

- Provider：Tavily Search HTTP API。
- 配置：`TAVILY_API_KEY`、可选 `TAVILY_BASE_URL`。
- 请求：Bearer 认证，`POST /search`，basic depth，最多 1-10 条。
- 输出：`WebSearchOutput(query, provider, status, results, error)`。
- 单条结果：title、url、content、score。
- 无 key、超时、非 2xx 或响应格式异常时返回 `status=unavailable`，不抛出导致 AgentLoop 退出，也不生成伪结果。

## 消费方

- `market_trend_research` 把真实结果序列化为带来源 URL 的 LLM evidence；unavailable 时保留当前中性降级。
- `exchange_rate` 只在搜索成功且存在 evidence 时调用 LLM 解析；否则明确报无法获取实时汇率。
- `price_compare` 异步调用 `exchange_rate`，按币种复用其内存缓存，不再使用静态 `app.recall.fx`。

## 测试

- 使用 `httpx.MockTransport` 验证请求、Bearer 认证、结果映射和无 key 降级。
- 趋势和汇率测试验证结构化 evidence。
- 比价测试 mock 汇率工具，验证 USD/CNY 排序。
- 全量 pytest、前端测试、build 和 Mock Demo 保持通过。
