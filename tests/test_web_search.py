import asyncio
import json

import httpx

from app.tools.web_search import (
    DeepSeekAnthropicWebSearchBackend,
    OpenAIResponsesWebSearchBackend,
    UnavailableWebSearchBackend,
    WebSearchOutput,
    get_web_search_backend,
    web_search,
)


def _deepseek_backend(
    handler,
) -> tuple[DeepSeekAnthropicWebSearchBackend, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        DeepSeekAnthropicWebSearchBackend(
            client=client,
            model="deepseek-v4-pro",
            api_key="test-key",
            base_url="https://api.deepseek.test/anthropic",
        ),
        client,
    )


class FakeResponse:
    output_text = "Demand for earbuds is growing."

    def model_dump(self):
        return {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": self.output_text,
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "Market report",
                                    "url": "https://example.com/report",
                                }
                            ],
                        }
                    ],
                }
            ]
        }


class FakeResponses:
    kwargs = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeResponse()


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


def test_openai_backend_uses_builtin_search_and_maps_citations() -> None:
    client = FakeClient()
    backend = OpenAIResponsesWebSearchBackend(client=client, model="gpt-5")
    result: WebSearchOutput = asyncio.run(
        backend.search("wireless earbuds trend", max_results=3)
    )
    assert client.responses.kwargs["tools"] == [{"type": "web_search"}]
    assert result.status == "ok"
    assert result.results[0].url == "https://example.com/report"
    assert result.results[0].content == "Demand for earbuds is growing."


def test_deepseek_backend_uses_server_search_and_maps_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srvtoolu_1",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "Report A",
                                "url": "https://a.test/report",
                                "encrypted_content": "opaque-a",
                            },
                            {
                                "type": "web_search_result",
                                "title": "Duplicate A",
                                "url": "https://a.test/report",
                                "encrypted_content": "opaque-duplicate",
                            },
                            {
                                "type": "web_search_result",
                                "title": "Report B",
                                "url": "https://b.test/report",
                                "encrypted_content": "opaque-b",
                            },
                        ],
                    },
                    {"type": "text", "text": "Current market evidence."},
                ],
            },
        )

    backend, client = _deepseek_backend(handler)
    try:
        result = asyncio.run(backend.search("earbuds trend", max_results=1))
    finally:
        asyncio.run(client.aclose())

    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == (
        "https://api.deepseek.test/anthropic/v1/messages"
    )
    assert requests[0].headers["x-api-key"] == "test-key"
    assert requests[0].headers["anthropic-version"] == "2023-06-01"
    assert payload["model"] == "deepseek-v4-pro"
    assert payload["tools"] == [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 1,
        }
    ]
    assert result.provider == "deepseek_anthropic"
    assert result.status == "ok"
    assert [item.url for item in result.results] == ["https://a.test/report"]
    assert result.results[0].content == "Current market evidence."


def test_deepseek_backend_continues_pause_turn_once() -> None:
    requests: list[httpx.Request] = []
    paused_content = [
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {
                    "type": "web_search_result",
                    "title": "Paused result",
                    "url": "https://paused.test/report",
                    "encrypted_content": "opaque",
                }
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"stop_reason": "pause_turn", "content": paused_content},
            )
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Final evidence."}],
            },
        )

    backend, client = _deepseek_backend(handler)
    try:
        result = asyncio.run(backend.search("paused query", max_results=3))
    finally:
        asyncio.run(client.aclose())

    assert len(requests) == 2
    continuation = json.loads(requests[1].content)
    assert continuation["messages"] == [
        {"role": "user", "content": "paused query"},
        {"role": "assistant", "content": paused_content},
    ]
    assert result.results[0].url == "https://paused.test/report"
    assert result.results[0].content == "Final evidence."


def test_deepseek_backend_redacts_http_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret-response test-key")

    backend, client = _deepseek_backend(handler)
    try:
        result = asyncio.run(backend.search("failing query", max_results=3))
    finally:
        asyncio.run(client.aclose())

    assert result.status == "unavailable"
    assert result.error == "DeepSeek web search failed: HTTP 401"
    assert "secret-response" not in result.error
    assert "test-key" not in result.error


def test_auto_backend_marks_deepseek_search_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("LLM_WEB_SEARCH_BACKEND", "auto")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    assert isinstance(get_web_search_backend(), UnavailableWebSearchBackend)
    result = asyncio.run(web_search.ainvoke({"query": "test"}))
    assert result.status == "unavailable"
    assert "built-in web search" in (result.error or "")


def test_auto_backend_selects_openai_responses(monkeypatch) -> None:
    monkeypatch.setenv("LLM_WEB_SEARCH_BACKEND", "auto")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL_NAME", "gpt-5")
    assert isinstance(get_web_search_backend(), OpenAIResponsesWebSearchBackend)
