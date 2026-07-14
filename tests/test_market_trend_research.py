import asyncio

from langchain_core.messages import AIMessage

from app.tools.market_trend_research import MarketTrendOutput, market_trend_research
from app.tools.web_search import SearchResult, WebSearchOutput


def test_market_trend_research_returns_structured_output(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    result: MarketTrendOutput = asyncio.run(
        market_trend_research.ainvoke({"category": "wireless earbuds"})
    )
    assert result.category == "wireless earbuds"
    assert 0 <= result.demand_score <= 1
    assert result.trend_summary
    assert isinstance(result.opportunity_gaps, list)


def test_market_trend_research_passes_source_attributed_evidence(monkeypatch) -> None:
    from app.tools import market_trend_research as module

    class FakeSearch:
        async def ainvoke(self, _payload):
            return WebSearchOutput(
                query="earbuds",
                status="ok",
                results=[
                    SearchResult(
                        title="Trend report",
                        url="https://example.com/trend",
                        content="Demand grew.",
                    )
                ],
            )

    class FakeLLM:
        messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return AIMessage(
                content='{"demand_score": 0.8, "trend_summary": "Growing", "opportunity_gaps": [], "keywords": []}'
            )

    fake_llm = FakeLLM()
    monkeypatch.setattr(module, "web_search", FakeSearch())
    monkeypatch.setattr(module, "get_llm", lambda: fake_llm)
    asyncio.run(module.market_trend_research.ainvoke({"category": "earbuds"}))
    assert "URL: https://example.com/trend" in fake_llm.messages[1][1]
