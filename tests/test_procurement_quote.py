"""Tests for procurement_quote tool."""

import asyncio

from app.tools import procurement_quote as module
from app.tools.procurement_quote import (
    ProcurementQuoteOutput,
    _extract_cny_candidates,
    _pick_quote,
    estimate_from_retail,
)
from app.tools.web_search import SearchResult, WebSearchOutput


def test_extract_cny_and_usd_prices() -> None:
    text = "1688 批发价 ¥18.5 / 另一家 22元，Alibaba about $3.2 USD"
    prices = _extract_cny_candidates(text)
    assert 18.5 in prices
    assert 22.0 in prices
    assert any(abs(p - 3.2 * 7.2) < 0.01 for p in prices)


def test_pick_quote_uses_median() -> None:
    assert _pick_quote([10.0, 100.0, 20.0]) == 20.0
    assert _pick_quote([16.8, 19.0]) == 17.9


def test_estimate_from_retail_usd() -> None:
    assert estimate_from_retail(amazon_price_usd=20.0, amazon_price_cny=None) == round(
        20 * 7.2 * 0.28, 2
    )


class FakeSearch:
    def __init__(self, result: WebSearchOutput) -> None:
        self._result = result

    async def ainvoke(self, payload):
        return self._result.model_copy(update={"query": payload["query"]})


def test_procurement_quote_parses_web_search(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "web_search",
        FakeSearch(
            WebSearchOutput(
                query="q",
                provider="test",
                status="ok",
                results=[
                    SearchResult(
                        title="1688 earbuds",
                        url="https://1688.example/1",
                        content="蓝牙耳机批发价 ¥16.8 起批量拿货",
                    ),
                    SearchResult(
                        title="工厂报价",
                        url="https://1688.example/2",
                        content="同款拿货价 19元/件 MOQ100",
                    ),
                ],
            )
        ),
    )
    result: ProcurementQuoteOutput = asyncio.run(
        module.procurement_quote.ainvoke(
            {
                "product_query": "wireless earbuds",
                "amazon_price_usd": 29.99,
                "quantity": 100,
            }
        )
    )
    assert result.source == "web_search"
    assert result.procurement_cost_cny == 17.9
    assert result.confidence >= 0.55
    assert result.evidence


def test_procurement_quote_falls_back_to_retail_estimate(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "web_search",
        FakeSearch(
            WebSearchOutput(
                query="q",
                provider="test",
                status="unavailable",
                error="timeout",
            )
        ),
    )
    result = asyncio.run(
        module.procurement_quote.ainvoke(
            {
                "product_query": "wireless earbuds",
                "amazon_price_usd": 25.0,
            }
        )
    )
    assert result.source == "retail_ratio_estimate"
    assert result.procurement_cost_cny == round(25 * 7.2 * 0.28, 2)
    assert result.confidence == 0.4


def test_procurement_quote_unavailable_without_anchor(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "web_search",
        FakeSearch(
            WebSearchOutput(
                query="q",
                provider="test",
                status="unavailable",
                error="no key",
            )
        ),
    )
    result = asyncio.run(
        module.procurement_quote.ainvoke({"product_query": "mystery gadget"})
    )
    assert result.source == "unavailable"
    assert result.procurement_cost_cny is None
