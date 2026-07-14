import asyncio
from decimal import Decimal

from app.data import Product
from app.tools.price_compare import PriceCompareOutput, price_compare


def test_price_compare_handles_product_input(monkeypatch) -> None:
    from app.tools import price_compare as module

    class FakeRate:
        async def ainvoke(self, _payload):
            return type("Rate", (), {"rate": 7.0})()

    monkeypatch.setattr(module, "exchange_rate", FakeRate())
    products = [
        Product(product_id="A1", title="One", category="x", price=Decimal("29.99"), platform="amazon", url="https://x/A1"),
        Product(product_id="A2", title="Two", category="x", price=Decimal("19.99"), platform="amazon", url="https://x/A2"),
    ]
    result: PriceCompareOutput = asyncio.run(
        price_compare.ainvoke(
            {"candidates": [p.model_dump(mode="json") for p in products], "top_n": 2}
        )
    )
    assert [point.item_id for point in result.ranked] == ["A2", "A1"]


def test_price_compare_uses_live_rate_for_mixed_currencies(monkeypatch) -> None:
    from app.tools import price_compare as module

    class FakeRate:
        async def ainvoke(self, payload):
            assert payload == {"source_currency": "USD", "target_currency": "CNY"}
            return type("Rate", (), {"rate": 5.0})()

    monkeypatch.setattr(module, "exchange_rate", FakeRate())
    result = asyncio.run(
        module.price_compare.ainvoke(
            {
                "candidates": [
                    {"item_id": "USD", "platform": "amazon", "title": "USD item", "price": 10, "currency": "USD"},
                    {"item_id": "CNY", "platform": "mock", "title": "CNY item", "price": 60, "currency": "CNY"},
                ],
                "base_currency": "CNY",
            }
        )
    )
    assert [point.item_id for point in result.ranked] == ["USD", "CNY"]
    assert result.ranked[0].price_cny == 50.0


def test_price_compare_extracts_product_weight_for_shipping() -> None:
    result = asyncio.run(
        price_compare.ainvoke(
            {
                "candidates": [
                    {
                        "item_id": "A1",
                        "platform": "amazon",
                        "title": "Light item",
                        "price": 70,
                        "currency": "CNY",
                        "attributes": {"weight": "200g"},
                    }
                ]
            }
        )
    )

    assert result.ranked[0].weight_kg == 0.2
