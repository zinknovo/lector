import asyncio

from app.tools.web_search import (
    OpenAIResponsesWebSearchBackend,
    UnavailableWebSearchBackend,
    WebSearchOutput,
    get_web_search_backend,
    web_search,
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
