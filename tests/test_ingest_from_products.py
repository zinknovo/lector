"""Tests for auto-ingesting category cards from product search results."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.data.models import Product
from app.recall.category_kb import CategoryCard
from app.recall.ingest_from_products import (
    build_category_cards_from_products,
    ingest_products_as_category_cards,
)
from app.tools import product_scraper as scraper_module
from app.tools.product_scraper import product_scraper
from scripts.etl.admit import admit


def _product(**overrides: Any) -> Product:
    base = {
        "product_id": "B0TEST",
        "title": "Wireless Earbuds ANC Sports Waterproof 40Hr Battery",
        "category": "electronics",
        "price": Decimal("24.99"),
        "platform": "amazon",
        "url": "https://example.com/p",
        "rating": 4.5,
        "review_count": 1000,
    }
    base.update(overrides)
    return Product(**base)


def test_build_cards_passes_admit_and_covers_three_types() -> None:
    products = [
        _product(product_id="A", title="ANC Noise Cancelling Wireless Earbuds", price=Decimal("29.99"), review_count=2000),
        _product(product_id="B", title="Sports Waterproof Bluetooth Earbuds IPX7", price=Decimal("19.99"), review_count=800),
        _product(product_id="C", title="Long Battery Playtime Wireless Headphones 60Hrs", price=Decimal("39.99"), review_count=500),
    ]
    cards = build_category_cards_from_products(
        "wireless earbuds",
        products,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    assert len(cards) == 3
    assert {c.card_type for c in cards} == {"bestseller", "attribute", "price_range"}
    assert all(c.category == "wireless earbuds" for c in cards)
    for card in cards:
        ok, reason = admit(card.model_dump())
        assert ok, reason


def test_build_cards_empty_products() -> None:
    assert build_category_cards_from_products("q", []) == []


def test_ingest_upserts_via_store() -> None:
    class FakeStore:
        def __init__(self) -> None:
            self.cards: list[CategoryCard] = []

        async def upsert_many(self, cards: list[CategoryCard]) -> int:
            self.cards = cards
            return len(cards)

        async def search(self, category: str, *, card_types=None, limit: int = 8):
            return self.cards

    store = FakeStore()
    written = asyncio.run(
        ingest_products_as_category_cards(
            "camping",
            [_product(title="Camping Tent Waterproof", product_id="1")],
            store=store,
        )
    )
    assert written == 3
    assert len(store.cards) == 3


def test_ingest_swallows_store_errors() -> None:
    class BoomStore:
        async def upsert_many(self, cards: list[CategoryCard]) -> int:
            raise RuntimeError("mongo down")

        async def search(self, category: str, *, card_types=None, limit: int = 8):
            return []

    written = asyncio.run(
        ingest_products_as_category_cards(
            "camping",
            [_product()],
            store=BoomStore(),
        )
    )
    assert written == 0


def test_product_scraper_auto_ingests(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_ingest(query: str, products, *, store=None) -> int:
        calls.append((query, len(products)))
        return 3

    monkeypatch.setattr(scraper_module, "ingest_products_as_category_cards", fake_ingest)

    result = asyncio.run(
        product_scraper.ainvoke(
            {"platform": "mock", "query": "camping", "max_results": 3}
        )
    )
    assert result.category_cards_upserted == 3
    assert calls == [("camping", 3)]
