"""Deterministic aggregation of product-selection evidence."""

import math
import time
from enum import Enum

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor
from app.tools.supplier_evaluator import RiskLevel


class Recommendation(str, Enum):
    RECOMMEND = "recommend"
    WATCH = "watch"
    REJECT = "reject"


class SelectionDecision(BaseModel):
    product_id: str
    title: str
    platform: str
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None
    selling_price_cny: float | None = None
    landed_cost_cny: float | None = None
    shipping_cost_cny: float | None = None
    eta_days: int | None = None
    total_cost_cny: float | None = None
    net_profit_cny: float | None = None
    profit_margin: float | None = None
    roi: float | None = None
    supplier_risk_score: float | None = None
    supplier_risk_level: RiskLevel | None = None
    market_score: float | None = None
    profit_score: float | None = None
    logistics_score: float | None = None
    supplier_score: float | None = None
    overall_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    recommendation: Recommendation
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)


_WEIGHTS = {
    "market": 0.30,
    "profit": 0.35,
    "logistics": 0.20,
    "supplier": 0.15,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _market_score(
    rating: float | None, review_count: int | None, sales: int | None
) -> float | None:
    values: list[float] = []
    if rating is not None:
        values.append(_clamp(rating / 5))
    if review_count is not None:
        values.append(_clamp(math.log10(review_count + 1) / 4))
    if sales is not None:
        values.append(_clamp(math.log10(sales + 1) / 4))
    return _average(values)


def _profit_score(
    profit_margin: float | None, roi: float | None, net_profit_cny: float | None
) -> float | None:
    values: list[float] = []
    if profit_margin is not None:
        values.append(_clamp(profit_margin / 0.30))
    if roi is not None:
        values.append(_clamp(roi / 0.50))
    if net_profit_cny is not None:
        values.append(_clamp(net_profit_cny / 100))
    return _average(values)


def _logistics_score(
    selling_price_cny: float | None,
    landed_cost_cny: float | None,
    shipping_cost_cny: float | None,
    eta_days: int | None,
) -> float | None:
    values: list[float] = []
    if selling_price_cny and landed_cost_cny is not None:
        headroom = (selling_price_cny - landed_cost_cny) / selling_price_cny
        values.append(_clamp(headroom / 0.30))
    if landed_cost_cny and shipping_cost_cny is not None:
        shipping_ratio = shipping_cost_cny / landed_cost_cny
        values.append(_clamp(1 - shipping_ratio / 0.20))
    if eta_days is not None:
        values.append(_clamp((30 - eta_days) / 20))
    return _average(values)


@tool
async def selection_decision(
    product_id: str,
    title: str,
    platform: str,
    rating: float | None = None,
    review_count: int | None = None,
    sales: int | None = None,
    selling_price_cny: float | None = None,
    landed_cost_cny: float | None = None,
    shipping_cost_cny: float | None = None,
    eta_days: int | None = None,
    total_cost_cny: float | None = None,
    net_profit_cny: float | None = None,
    profit_margin: float | None = None,
    roi: float | None = None,
    supplier_risk_score: float | None = None,
    supplier_risk_level: RiskLevel | None = None,
) -> SelectionDecision:
    """Aggregate existing market, profit, logistics and supplier evidence."""
    await monitor.report_tool_start("selection_decision", {"product_id": product_id})
    started_at = time.time()
    scores = {
        "market": _market_score(rating, review_count, sales),
        "profit": _profit_score(profit_margin, roi, net_profit_cny),
        "logistics": _logistics_score(
            selling_price_cny, landed_cost_cny, shipping_cost_cny, eta_days
        ),
        "supplier": (
            _clamp(1 - supplier_risk_score)
            if supplier_risk_score is not None
            else None
        ),
    }
    available_weight = sum(
        _WEIGHTS[name] for name, score in scores.items() if score is not None
    )
    weighted_score = sum(
        _WEIGHTS[name] * score
        for name, score in scores.items()
        if score is not None
    )
    overall_score = weighted_score / available_weight if available_weight else 0.0
    missing_data = [name for name, score in scores.items() if score is None]
    reasons: list[str] = []
    risks: list[str] = []
    if scores["market"] is not None and scores["market"] >= 0.7:
        reasons.append("市场表现较强")
    if scores["profit"] is not None and scores["profit"] >= 0.7:
        reasons.append("利润能力达到目标")
    if scores["logistics"] is not None and scores["logistics"] >= 0.7:
        reasons.append("物流与到手成本可控")
    if supplier_risk_level == RiskLevel.HIGH:
        risks.append("供应商风险为 high")
        recommendation = Recommendation.REJECT
    elif overall_score < 0.45:
        risks.append("综合评分低于准入线")
        recommendation = Recommendation.REJECT
    elif (
        overall_score >= 0.70
        and available_weight >= 0.80
        and scores["profit"] is not None
        and scores["supplier"] is not None
    ):
        recommendation = Recommendation.RECOMMEND
    else:
        recommendation = Recommendation.WATCH
        if missing_data:
            risks.append("关键决策数据不完整")
    await monitor.report_tool_end(
        "selection_decision", int((time.time() - started_at) * 1000)
    )
    return SelectionDecision(
        product_id=product_id,
        title=title,
        platform=platform,
        rating=rating,
        review_count=review_count,
        sales=sales,
        selling_price_cny=selling_price_cny,
        landed_cost_cny=landed_cost_cny,
        shipping_cost_cny=shipping_cost_cny,
        eta_days=eta_days,
        total_cost_cny=total_cost_cny,
        net_profit_cny=net_profit_cny,
        profit_margin=profit_margin,
        roi=roi,
        supplier_risk_score=supplier_risk_score,
        supplier_risk_level=supplier_risk_level,
        market_score=round(scores["market"], 4) if scores["market"] is not None else None,
        profit_score=round(scores["profit"], 4) if scores["profit"] is not None else None,
        logistics_score=round(scores["logistics"], 4) if scores["logistics"] is not None else None,
        supplier_score=round(scores["supplier"], 4) if scores["supplier"] is not None else None,
        overall_score=round(overall_score, 4),
        confidence=round(available_weight, 4),
        recommendation=recommendation,
        reasons=reasons,
        risks=risks,
        missing_data=missing_data,
    )
