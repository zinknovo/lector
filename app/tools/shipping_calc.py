"""运费 + 关税估算工具。"""

import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor
from app.recall.duty import estimate_duty
from app.recall.shipping import estimate_shipping
from app.tools.price_compare import PricePoint


class LandedCost(BaseModel):
    """单件商品的到手成本。"""

    item_id: str
    platform: str
    price_cny: float
    shipping_cny: float
    duty_cny: float
    landed_cny: float  # 到手价 = 商品 + 运费 + 关税
    eta_days: int  # 物流时效预估
    duty_tier: Literal["免征", "标准", "高税"]
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None


class ShippingCalcOutput(BaseModel):
    destination: str
    items: list[LandedCost]


def _guess_weight_kg(_p: PricePoint) -> float:
    """从 PricePoint 反推出大致重量。真实项目应来自 Candidate.attributes。"""
    # 这里给一个占位值；后续 CategoryInsight 会把品类典型重量补回来
    return 0.5


@tool
async def shipping_calc(
    points: list[PricePoint],
    destination: str = "CN",
) -> ShippingCalcOutput:
    """为已比价的候选估算到手价（含国际运费 + 综合税）。

    Args:
        points: 来自 PriceCompare.ranked 的子集（建议直接传 ranked，不超过 30 件）。
        destination: 收货国家 ISO 码，默认中国大陆。

    Returns:
        items: 每件候选的 LandedCost，按 landed_cny 升序。
    """
    await monitor.report_tool_start("shipping_calc", {
        "items_count": len(points),
        "destination": destination,
    })
    t0 = time.time()

    landed: list[LandedCost] = []
    for p in points:
        weight = _guess_weight_kg(p)
        shipping_cny, eta = estimate_shipping(weight, p.platform)
        duty_cny, duty_tier = estimate_duty(p.price_cny, p.platform)
        total = round(p.price_cny + shipping_cny + duty_cny, 2)
        landed.append(LandedCost(
            item_id=p.item_id,
            platform=p.platform,
            price_cny=p.price_cny,
            shipping_cny=shipping_cny,
            duty_cny=duty_cny,
            landed_cny=total,
            eta_days=eta,
            duty_tier=duty_tier,
            rating=p.rating,
            review_count=p.review_count,
            sales=p.sales,
        ))

    landed.sort(key=lambda x: x.landed_cny)

    await monitor.report_tool_end("shipping_calc", int((time.time() - t0) * 1000))
    return ShippingCalcOutput(destination=destination, items=landed)
