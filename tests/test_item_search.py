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


def test_item_search_amazon_uses_apify_source(monkeypatch) -> None:
    from app.data import ApifyAmazonDataSource

    # 显式提供 token，避免依赖其它测试模块加载 .env 的副作用（单独跑本文件也要过）
    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
    source = item_search_module._source_for("amazon")
    assert isinstance(source, ApifyAmazonDataSource)


def test_item_search_excludes_category_mismatch(monkeypatch) -> None:
    """品类不一致的相近品被排除并带原因；品类知识卡只灌入保留的候选。"""
    from decimal import Decimal

    from app.data import Product

    def product(product_id: str, title: str) -> Product:
        return Product(
            product_id=product_id,
            title=title,
            category="kitchen",
            price=Decimal("39.9"),
            platform="mock",
            url=f"https://example.com/{product_id}",
        )

    class StubSource:
        async def search(self, _query, **_filters):
            return [
                product("OK-1", "316不锈钢保温杯 商务"),
                product("BAD-1", "紫砂茶杯 景德镇手工"),
            ]

    ingested: list[list[str]] = []

    async def fake_ingest(_query, products, *, store=None) -> int:
        ingested.append([item.product_id for item in products])
        return len(products)

    monkeypatch.setattr(item_search_module, "_source_for", lambda platform: StubSource())
    monkeypatch.setattr(
        item_search_module, "ingest_products_as_category_cards", fake_ingest
    )

    result = asyncio.run(
        item_search.ainvoke({"query": "保温杯", "platform": "mock"})
    )

    assert [candidate.item_id for candidate in result.candidates] == ["OK-1"]
    assert [excluded.item_id for excluded in result.excluded] == ["BAD-1"]
    assert result.excluded[0].reason_code == "category_mismatch"
    assert ingested == [["OK-1"]]
