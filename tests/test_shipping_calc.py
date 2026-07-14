import asyncio

from app.tools.shipping_calc import ShippingCalcOutput, shipping_calc


def test_shipping_calc_forwards_selection_metrics() -> None:
    result: ShippingCalcOutput = asyncio.run(
        shipping_calc.ainvoke(
            {
                "points": [
                    {
                        "item_id": "A1",
                        "platform": "amazon",
                        "title": "Test",
                        "price_local": 10,
                        "currency_local": "USD",
                        "price_cny": 70,
                        "rating": 4.8,
                        "review_count": 900,
                        "sales": 2000,
                    }
                ]
            }
        )
    )
    item = result.items[0]
    assert (item.rating, item.review_count, item.sales) == (4.8, 900, 2000)


def test_shipping_calc_uses_forwarded_product_weight() -> None:
    result: ShippingCalcOutput = asyncio.run(
        shipping_calc.ainvoke(
            {
                "points": [
                    {
                        "item_id": "A1",
                        "platform": "amazon",
                        "title": "Light item",
                        "price_local": 10,
                        "currency_local": "CNY",
                        "price_cny": 70,
                        "weight_kg": 0.2,
                    }
                ]
            }
        )
    )

    assert result.items[0].weight_kg == 0.2
    assert result.items[0].shipping_cny == 85
