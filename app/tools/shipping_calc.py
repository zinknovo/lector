"""卖家头程运费 + 进口税参考（中国货源 → 目标销售市场）。"""

import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor
from app.recall.duty import estimate_duty
from app.recall.shipping import estimate_shipping
from app.tools.price_compare import PricePoint


class LandedCost(BaseModel):
    """单件候选的售价参考 + 中国发往目标市场的头程成本。"""

    item_id: str
    platform: str
    price_cny: float  # 目标市场售价（归一 CNY），不是采购成本
    shipping_cny: float  # 中国 → 目标市场头程运费
    duty_cny: float  # 进口税参考（按估算货值）
    landed_cny: float  # 头程综合成本 = 运费 + 关税（不含采购、不含售价）
    eta_days: int
    duty_tier: Literal["免征", "标准", "高税"]
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None
    weight_kg: float | None = None


class ShippingCalcOutput(BaseModel):
    destination: str
    items: list[LandedCost]


def _weight_kg(point: PricePoint) -> float:
    return point.weight_kg if point.weight_kg is not None else 0.5


@tool
async def shipping_calc(
    points: list[PricePoint],
    destination: str = "US",
    declared_value_ratio: float = 0.28,
) -> ShippingCalcOutput:
    """估算中国货源发往目标销售市场的头程运费与进口税参考。

    业务方向是「中国卖全球」（如 Amazon 美国站），不是「从 Amazon 买回中国」。
    - points.price_cny：目标市场售价参考
    - shipping_cny / duty_cny：头程成本，供 profit_calculator.shipping_cost 使用
    - landed_cny：仅 = 运费 + 关税（不含售价、不含采购价）
    - destination：默认 US；美国站选品必须用 US，禁止默认成 CN

    declared_value_ratio：用售价估算申报货值的比例（无真实采购价时的 MVP 近似）。
    """
    destination = (destination or "US").upper()
    ratio = min(max(declared_value_ratio, 0.05), 1.0)
    await monitor.report_tool_start(
        "shipping_calc",
        {
            "items_count": len(points),
            "destination": destination,
        },
    )
    t0 = time.time()

    landed: list[LandedCost] = []
    for p in points:
        weight = _weight_kg(p)
        shipping_cny, eta = estimate_shipping(
            weight, p.platform, destination=destination
        )
        declared = round(p.price_cny * ratio, 2)
        duty_cny, duty_tier = estimate_duty(
            declared, p.platform, destination=destination
        )
        outbound = round(shipping_cny + duty_cny, 2)
        landed.append(
            LandedCost(
                item_id=p.item_id,
                platform=p.platform,
                price_cny=p.price_cny,
                shipping_cny=shipping_cny,
                duty_cny=duty_cny,
                landed_cny=outbound,
                eta_days=eta,
                duty_tier=duty_tier,
                rating=p.rating,
                review_count=p.review_count,
                sales=p.sales,
                weight_kg=p.weight_kg,
            )
        )

    landed.sort(key=lambda x: x.landed_cny)

    await monitor.report_tool_end("shipping_calc", int((time.time() - t0) * 1000))
    return ShippingCalcOutput(destination=destination, items=landed)
