import asyncio
from typing import Literal

from app.tools.category_insight import CategoryInsightOutput, PriceTier
from app.tools.item_picker import _check_preferences, _score, item_picker
from app.tools.shipping_calc import LandedCost


def _cost(
    item_id: str,
    *,
    platform: str = "shopee",
    landed_cny: float = 199.0,
    eta_days: int = 10,
    duty_tier: Literal["免征", "标准", "高税"] = "免征",
    rating: float | None = None,
    review_count: int | None = None,
    sales: int | None = None,
) -> LandedCost:
    return LandedCost(
        item_id=item_id,
        platform=platform,
        price_cny=150,
        shipping_cny=49,
        duty_cny=0,
        landed_cny=landed_cny,
        eta_days=eta_days,
        duty_tier=duty_tier,
        rating=rating,
        review_count=review_count,
        sales=sales,
    )


def _insight() -> CategoryInsightOutput:
    return CategoryInsightOutput(
        category="旅行背包",
        components=[],
        bestsellers=[],
        attributes=[],
        price_tiers=[
            PriceTier(tier="budget", range_cny=(100, 300), notes="中档 100-300")
        ],
        confidence=1.0,
    )


def test_hard_preference_rejects_matching_plastic_item() -> None:
    flags = _check_preferences(
        _cost("EBAY-PLASTIC", platform="ebay"), ["不要塑料"]
    )

    assert flags == ["HARD_FAIL:塑料，命中用户黑名单"]


def test_score_combines_price_shipping_duty_and_product_metrics() -> None:
    score, reasons = _score(
        _cost("S1", rating=4.7, review_count=1200, sales=3000),
        _insight(),
        [],
    )

    assert score == 0.8
    assert len(reasons) == 3
    assert reasons[0].startswith("到手价 199.0 落在中档")
    assert reasons[1] == "10 天到手"
    assert reasons[2] == "跨境直邮免税"


def test_item_picker_filters_sorts_and_limits_results() -> None:
    async def run():
        return await item_picker.ainvoke(
            {
                "landed": [
                    _cost("EBAY-PLASTIC", platform="ebay").model_dump(),
                    _cost("SLOW", platform="amazon", landed_cny=500, eta_days=20, duty_tier="标准").model_dump(),
                    _cost("BEST").model_dump(),
                ],
                "insight": _insight().model_dump(),
                "user_preferences": ["不要塑料", "偏好小众"],
                "top_n": 1,
            }
        )

    result = asyncio.run(run())

    assert [pick.item_id for pick in result.picks] == ["BEST"]
    assert result.rejected_brief == ["EBAY-PLASTIC: 塑料，命中用户黑名单"]
