# Lector 模型内置搜索设计

## 目标

搜索由当前模型厂商的内置工具执行，不引入 Tavily 等独立搜索供应商。Lector 通过稳定接口隔离不同模型厂商的请求和响应格式。

## 接口

`BuiltInWebSearchBackend.search(query, max_results) -> WebSearchOutput` 是唯一模型搜索边界。

- `OpenAIResponsesWebSearchBackend`：调用 Responses API，启用 `tools=[{"type": "web_search"}]`，从 `url_citation` annotations 提取来源。
- `UnavailableWebSearchBackend`：当前模型端点没有已实现的内置搜索能力时返回 `status=unavailable`。
- `get_web_search_backend()`：读取 `LLM_WEB_SEARCH_BACKEND=auto|openai_responses|none`。auto 仅在 OpenAI 官方端点选择 Responses adapter。

所有 adapter 复用 `LLM_API_KEY`、`LLM_MODEL_NAME`、`LLM_BASE_URL`，不增加独立搜索账号。

## 兼容性

- DeepSeek 官方 API 当前只有开发者函数调用，auto 返回 unavailable。
- OpenAI 官方 Responses API 可直接使用内置 web_search。
- Claude/Gemini 后续各自新增 adapter，不改变上层工具。
- `market_trend_research`、`exchange_rate`、`price_compare` 继续消费 `WebSearchOutput`，不感知厂商。

## 验证

- fake Responses client 验证工具参数与 citation 映射。
- backend factory 验证 auto/显式选择与 unavailable。
- 删除所有 Tavily 配置、代码和文档引用。
- 后端、前端、build、Mock Demo 全部通过。
