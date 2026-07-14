import asyncio

from app.tools.market_trend_research import MarketTrendOutput, market_trend_research


def test_market_trend_research_returns_structured_output() -> None:
    result: MarketTrendOutput = asyncio.run(
        market_trend_research.ainvoke({"category": "wireless earbuds"})
    )
    assert result.category == "wireless earbuds"
    assert 0 <= result.demand_score <= 1
    assert result.trend_summary
    assert isinstance(result.opportunity_gaps, list)
