# Lector 模型内置搜索设计

## 目标

搜索由当前模型厂商的内置工具执行，不引入 Tavily 等独立搜索供应商。Lector 通过稳定接口隔离不同模型厂商的请求和响应格式。

## 接口

`BuiltInWebSearchBackend.search(query, max_results) -> WebSearchOutput` 是唯一模型搜索边界。

- `OpenAIResponsesWebSearchBackend`：调用 Responses API，启用 `tools=[{"type": "web_search"}]`，从 `url_citation` annotations 提取来源。
- `DeepSeekAnthropicWebSearchBackend`：仅搜索工具走 DeepSeek 的 Anthropic 兼容
  `Messages API`，启用 `web_search_20250305` 服务端工具；主模型调用仍走现有
  OpenAI Chat Completions 兼容接口。
- `UnavailableWebSearchBackend`：当前模型端点没有已实现的内置搜索能力时返回 `status=unavailable`。
- `get_web_search_backend()`：读取
  `LLM_WEB_SEARCH_BACKEND=auto|openai_responses|deepseek_anthropic|none`。`auto`
  在 OpenAI 官方端点选择 Responses adapter，在 DeepSeek 官方端点选择 Anthropic
  adapter，其他端点返回 unavailable。

所有 adapter 复用 `LLM_API_KEY` 和 `LLM_MODEL_NAME`，不增加独立搜索账号。
DeepSeek 搜索地址默认为 `https://api.deepseek.com/anthropic/v1/messages`，可通过
`DEEPSEEK_ANTHROPIC_BASE_URL` 覆盖协议根地址，便于测试和兼容代理。

## DeepSeek 请求与响应

请求使用现有 `httpx`，不新增 Anthropic SDK：

```json
{
  "model": "deepseek-v4-pro",
  "max_tokens": 2048,
  "tools": [{
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 1
  }],
  "messages": [{"role": "user", "content": "搜索词"}]
}
```

认证使用现有 DeepSeek Key，通过 `x-api-key` 发送，并带
`anthropic-version: 2023-06-01`。响应解析规则固定为：

1. 从 `web_search_tool_result.content` 中提取 `web_search_result` 的标题和 URL。
2. 从 `text` 内容块提取模型基于搜索结果生成的摘要，作为每条结果的 `content`；
   不把不可读的 `encrypted_content` 当摘要。
3. 按 URL 去重并应用 `max_results`。
4. 如果返回 `pause_turn`，原样追加 assistant 内容并最多续传一次，防止无限循环。
5. 没有 URL、HTTP 非成功、超时或响应结构错误时返回 `status=unavailable`，错误信息
   只包含异常类型或 HTTP 状态，不包含 Key 和完整响应体。

## 兼容性

- DeepSeek OpenAI Chat Completions 兼容层不提供 Responses 内置搜索；搜索 adapter
  使用同一 DeepSeek 服务的 Anthropic 兼容层，不调用 Anthropic 模型或账号。
- OpenAI 官方 Responses API 可直接使用内置 web_search。
- Claude/Gemini 后续各自新增 adapter，不改变上层工具。
- `market_trend_research`、`exchange_rate`、`price_compare` 继续消费 `WebSearchOutput`，不感知厂商。

## 验证

- fake Responses client 验证工具参数与 citation 映射。
- `httpx.MockTransport` 验证 DeepSeek 请求头、服务端工具参数、结果去重、limit、
  `pause_turn` 续传和安全失败语义。
- backend factory 验证 auto/显式选择与 unavailable。
- 使用当前 DeepSeek Key 做一次真实搜索 smoke，确认返回至少一个带 URL 的结果；测试
  只记录 provider、状态和 URL，不输出 Key 或完整搜索正文。
- 删除所有 Tavily 配置、代码和文档引用。
- 后端、前端、build、Mock Demo 全部通过。
