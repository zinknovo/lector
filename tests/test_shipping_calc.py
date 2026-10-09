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
    # 0.2kg → US 头程最低档
    assert result.items[0].shipping_cny == 18
    assert result.destination == "US"
    # landed = 运费 + 关税，不含售价
    declared = round(70 * 0.28, 2)
    duty = round(declared * 0.08, 2)
    assert result.items[0].duty_cny == duty
    assert result.items[0].landed_cny == round(18 + duty, 2)


def _point(item_id: str = "A1", price_cny: float = 70.0) -> dict:
    return {
        "item_id": item_id,
        "platform": "amazon",
        "title": "Test",
        "price_local": 10,
        "currency_local": "CNY",
        "price_cny": price_cny,
    }


def test_unknown_destination_reports_unavailable_without_fabricating() -> None:
    result = asyncio.run(
        shipping_calc.ainvoke({"points": [_point()], "destination": "BR"})
    )
    assert result.items == []
    assert len(result.unavailable) == 1
    assert result.unavailable[0].item_id == "A1"
    assert "没有 BR 的成本口径" in result.unavailable[0].reason


def test_japan_uses_japan_caliber_not_us(tmp_path) -> None:
    from app.api.context import thread_scope
    from app.evidence.store import EvidenceStore

    point = _point()
    point["weight_kg"] = 0.2  # 命中 JP 表最低档（0kg 档 15 元 / 12 天）
    with thread_scope("t-jp", tmp_path):
        result = asyncio.run(
            shipping_calc.ainvoke({"points": [point], "destination": "JP"})
        )

    item = result.items[0]
    assert item.shipping_cny == 15  # JP 表最低档，而不是 US 的 18
    declared = round(70 * 0.28, 2)
    assert item.duty_cny == round(declared * 0.08, 2)
    assert item.eta_days == 12

    evidence = EvidenceStore(tmp_path / "evidence.jsonl").latest(
        field="landed_cost_cny", product_id="A1"
    )
    assert evidence is not None
    assert "成本表 v1.1" in evidence.detail
    assert "粗估" in evidence.detail


def test_unknown_destination_records_missing_evidence(tmp_path) -> None:
    from app.api.context import thread_scope
    from app.evidence.store import EvidenceStore

    with thread_scope("t-br", tmp_path):
        asyncio.run(
            shipping_calc.ainvoke({"points": [_point()], "destination": "BR"})
        )

    evidence = EvidenceStore(tmp_path / "evidence.jsonl").latest(
        field="landed_cost_cny", product_id="A1"
    )
    assert evidence is not None
    assert evidence.method.value == "missing"
    assert "无该市场成本口径" in evidence.detail


def test_estimate_shipping_raises_for_unknown_destination() -> None:
    import pytest

    from app.recall.cost_tables import UnknownDestinationError
    from app.recall.shipping import estimate_shipping

    with pytest.raises(UnknownDestinationError, match="BR"):
        estimate_shipping(0.5, destination="BR")
