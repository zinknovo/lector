import asyncio
from unittest.mock import AsyncMock

from app.agent import item_search as item_search_module
from app.agent.item_search import ItemSearchOutput, item_search
from app.data import MockProductDataSource


def test_item_search_returns_candidates_from_mock() -> None:
    result: ItemSearchOutput = asyncio.run(
        item_search.ainvoke(
            {"query": "camping", "platform": "mock", "top_k": 3}
        )
    )
    assert len(result.candidates) == 3
    assert all(candidate.platform == "mock" for candidate in result.candidates)


def test_item_search_carries_product_metrics() -> None:
    result: ItemSearchOutput = asyncio.run(
        item_search.ainvoke({"query": "earbuds", "platform": "mock"})
    )
    candidate = result.candidates[0]
    assert candidate.review_count == 3400
    assert candidate.sales == 5600
    assert candidate.seller == "SoundWave"


def test_item_search_auto_ingests_category_cards(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_ingest(query: str, products, *, store=None) -> int:
        calls.append((query, len(products)))
        return 3

    monkeypatch.setattr(
        item_search_module, "ingest_products_as_category_cards", fake_ingest
    )
    monkeypatch.setattr(
        item_search_module,
        "_source_for",
        lambda platform: MockProductDataSource(),
    )

    result = asyncio.run(
        item_search.ainvoke(
            {"query": "camping", "platform": "mock", "top_k": 3}
        )
    )
    assert result.category_cards_upserted == 3
    assert calls and calls[0][0] == "camping"
    assert calls[0][1] == len(result.candidates) == 3


def test_item_search_amazon_uses_apify_source() -> None:
    from app.data import ApifyAmazonDataSource

    source = item_search_module._source_for("amazon")
    assert isinstance(source, ApifyAmazonDataSource)
