"""Select a small set of products from landed-cost candidates."""

import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor
from app.tools.category_insight import CategoryInsightOutput
from app.tools.shipping_calc import LandedCost


class PickedItem(BaseModel):
    item_id: str
    title: str | None = None
    platform: str
    landed_cny: float
    score: float
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class ItemPickerOutput(BaseModel):
    picks: list[PickedItem]
    rejected_brief: list[str]


@tool
async def item_picker(
    landed: list[LandedCost],
    insight: CategoryInsightOutput | None = None,
    user_preferences: list[str] | None = None,
    top_n: int = 3,
) -> ItemPickerOutput:
    """从到手价 Top-N 候选中精挑 1-3 件最契合用户的商品。"""
    await monitor.report_tool_start(
        "item_picker",
        {
            "landed_count": len(landed),
            "preferences": user_preferences or [],
        },
    )
    t0 = time.time()

    rejected: list[str] = []
    candidates: list[PickedItem] = []
    prefs = user_preferences or []

    for cost in landed:
        flags = _check_preferences(cost, prefs)
        hard_fail = next(
            (flag for flag in flags if flag.startswith("HARD_FAIL:")), None
        )
        if hard_fail is not None:
            rejected.append(f"{cost.item_id}: {hard_fail.split(':', 1)[1]}")
            continue

        score, reasons = _score(cost, insight, prefs)
        candidates.append(
            PickedItem(
                item_id=cost.item_id,
                title=None,
                platform=cost.platform,
                landed_cny=cost.landed_cny,
                score=score,
                reasons=reasons,
                flags=flags,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    picks = candidates[: max(0, min(top_n, 3))]

    await monitor.report_tool_end(
        "item_picker", int((time.time() - t0) * 1000)
    )
    return ItemPickerOutput(picks=picks, rejected_brief=rejected[:8])


def _check_preferences(cost: LandedCost, prefs: list[str]) -> list[str]:
    """硬约束走 HARD_FAIL，软偏好走普通 flag。"""
    flags: list[str] = []
    if any("不要塑料" in pref for pref in prefs):
        if cost.platform == "ebay" and cost.item_id.endswith("-PLASTIC"):
            flags.append("HARD_FAIL:塑料，命中用户黑名单")
    return flags


def _score(
    cost: LandedCost,
    insight: CategoryInsightOutput | None,
    prefs: list[str],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if insight and insight.price_tiers:
        budget_tier = next(
            (tier for tier in insight.price_tiers if tier.tier == "budget"), None
        )
        if (
            budget_tier
            and budget_tier.range_cny[0]
            <= cost.landed_cny
            <= budget_tier.range_cny[1]
        ):
            score += 0.25
            reasons.append(
                f"到手价 {cost.landed_cny} 落在中档 {budget_tier.range_cny}"
            )

    if cost.eta_days <= 12:
        score += 0.15
        reasons.append(f"{cost.eta_days} 天到手")

    if cost.duty_tier == "免征":
        score += 0.1
        reasons.append("跨境直邮免税")

    if cost.rating is not None and cost.rating >= 4.5:
        score += 0.15
        reasons.append(f"评分 {cost.rating}")

    if cost.review_count is not None and cost.review_count >= 500:
        score += 0.1
        reasons.append(f"{cost.review_count} 条评价")

    if cost.sales is not None and cost.sales >= 1000:
        score += 0.05
        reasons.append(f"销量 {cost.sales}")

    return round(score, 2), reasons[:3]
