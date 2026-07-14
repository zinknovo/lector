import asyncio
import json

import httpx

from app.tools.web_search import WebSearchOutput, _search_tavily, web_search


def test_tavily_search_maps_structured_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tvly-test"
        payload = json.loads(request.content)
        assert payload["query"] == "wireless earbuds trend"
        assert payload["max_results"] == 2
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Market report",
                        "url": "https://example.com/report",
                        "content": "Demand increased.",
                        "score": 0.91,
                    }
                ]
            },
        )

    async def run() -> WebSearchOutput:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await _search_tavily(
                "wireless earbuds trend",
                max_results=2,
                api_key="tvly-test",
                base_url="https://api.tavily.com",
                client=client,
            )

    result = asyncio.run(run())
    assert result.status == "ok"
    assert result.results[0].url == "https://example.com/report"
    assert result.results[0].score == 0.91


def test_web_search_without_key_returns_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result = asyncio.run(web_search.ainvoke({"query": "test"}))
    assert result.status == "unavailable"
    assert result.results == []
    assert "TAVILY_API_KEY" in (result.error or "")
