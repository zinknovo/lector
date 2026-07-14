import asyncio
from decimal import Decimal

from app.data import Product
from app.tools.price_compare import PriceCompareOutput, price_compare


def test_price_compare_handles_product_input() -> None:
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
