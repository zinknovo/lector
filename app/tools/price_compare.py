"""跨平台候选商品比价工具。"""

import re
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.item_search import Candidate
from app.api.monitor import monitor
from app.data import Product
from app.tools.exchange_rate import exchange_rate
from app.tools.market_price_search import PriceEvidence


class PricePoint(BaseModel):
    """单个平台的价格点。"""

    item_id: str
    platform: str
    title: str
    price_local: float
    currency_local: str
    price_cny: float  # 归一后的 CNY 价格（仅商品本体）
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    note: str | None = None  # 例如 "一套 3 件，等价单件 ~80"


class PriceCompareOutput(BaseModel):
    base_currency: str = "CNY"
    ranked: list[PricePoint]
    cheapest_per_platform: dict[str, str]  # {"amazon": "A1", "shopee": "S2"}


def _pack_note(c: Candidate) -> str | None:
    """从 attributes 中识别"一套 N 件"这类信息。"""
    pack_size = c.attributes.get("pack_size")
    if isinstance(pack_size, int) and pack_size > 1:
        return f"一套 {pack_size} 件，等价单件 {round(c.price / pack_size, 2)} {c.currency}"
    return None


def _extract_weight_kg(attributes: dict[str, object]) -> float | None:
    raw = attributes.get("weight_kg", attributes.get("weight"))
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else None
    if not isinstance(raw, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(kg|g)?\s*", raw.lower())
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2) == "g":
        value /= 1000
    return value if value > 0 else None


def _to_candidate(
    value: Candidate | Product | PriceEvidence,
) -> Candidate:
    if isinstance(value, Candidate):
        return value
    if isinstance(value, PriceEvidence):
        # PriceEvidence doesn't carry a full SKU title/attributes; we keep title minimal
        # for downstream tools that only need an ID and a currency-accurate price.
        evidence_id = value.item_id or f"web_price_{abs(hash(value.source_url))}"
        return Candidate(
            item_id=evidence_id,
            platform=value.platform,
            title=value.source_name or "web_price_evidence",
            price=float(value.price_local),
            currency=str(value.currency_local).upper(),
            rating=None,
            review_count=None,
            sales=None,
            image_url=None,
            seller=None,
            attributes={},
        )
    return Candidate(
        item_id=value.product_id,
        platform=value.platform,
        title=value.title,
        price=float(str(value.price)),
        currency="USD" if value.platform == "amazon" else "CNY",
        rating=value.rating,
        review_count=value.review_count,
        sales=value.sales_volume,
        image_url=value.image_url,
        seller=value.seller,
        attributes=value.attributes,
    )


@tool
async def price_compare(
    candidates: list[Candidate | Product | PriceEvidence],
    base_currency: str = "CNY",
    top_n: int = 12,
) -> PriceCompareOutput:
    """跨平台候选商品比价，输出币种归一后的排序。

    Args:
        candidates: 来自 ItemSearch 合流后的候选集（最多接受 100 件）。
        base_currency: 归一目标币种，默认人民币。
        top_n: 仅返回排序后的前 N 件，默认 12，最大 30。

    Returns:
        ranked: 按 price_cny 升序的 PricePoint 列表。
        cheapest_per_platform: 每个平台的最便宜 item_id，便于 ShippingCalc 使用。
    """
    top_n = min(top_n, 30)
    normalized = [_to_candidate(candidate) for candidate in candidates[:100]]
    await monitor.report_tool_start("price_compare", {
        "candidates_count": len(normalized),
        "base_currency": base_currency,
    })
    t0 = time.time()

    points: list[PricePoint] = []
    rates: dict[str, float] = {base_currency.upper(): 1.0}
    for c in normalized:
        try:
            currency = c.currency.upper()
            if currency not in rates:
                rate_result = await exchange_rate.ainvoke(
                    {
                        "source_currency": currency,
                        "target_currency": base_currency.upper(),
                    }
                )
                rates[currency] = rate_result.rate
            price_base = c.price * rates[currency]
        except (RuntimeError, ValueError):
            continue
        points.append(PricePoint(
            item_id=c.item_id,
            platform=c.platform,
            title=c.title,
            price_local=c.price,
            currency_local=c.currency,
            price_cny=round(price_base, 2),
            rating=c.rating,
            review_count=c.review_count,
            sales=c.sales,
            weight_kg=_extract_weight_kg(c.attributes),
            note=_pack_note(c),
        ))

    points.sort(key=lambda p: p.price_cny)
    ranked = points[:top_n]

    cheapest: dict[str, str] = {}
    for p in points:
        if p.platform not in cheapest:
            cheapest[p.platform] = p.item_id

    await monitor.report_tool_end("price_compare", int((time.time() - t0) * 1000))
    return PriceCompareOutput(
        base_currency=base_currency,
        ranked=ranked,
        cheapest_per_platform=cheapest,
    )
