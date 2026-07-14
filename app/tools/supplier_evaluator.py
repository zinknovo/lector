"""Rule-based supplier risk evaluation for sourcing decisions."""

import time
from enum import Enum

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SupplierEvalOutput(BaseModel):
    seller: str
    platform: str
    risk_score: float = Field(ge=0, le=1)
    risk_level: RiskLevel
    notes: list[str]


@tool
async def supplier_evaluator(
    seller: str, platform: str, evidence: list[str] | None = None
) -> SupplierEvalOutput:
    """Evaluate supplier risk from platform context and supplied evidence."""
    await monitor.report_tool_start(
        "supplier_evaluator", {"seller": seller, "platform": platform}
    )
    started_at = time.time()
    score = 0.5
    notes: list[str] = []
    if platform.lower() in {"amazon", "ebay"}:
        score -= 0.1
        notes.append(f"{platform} 有较成熟的卖家评价体系")
    elif platform.lower() in {"aliexpress", "shopee"}:
        score += 0.1
        notes.append("跨境卖家稳定性差异较大，建议小单验证")
    if len(seller.strip()) > 3:
        score -= 0.05
        notes.append("卖家名称信息完整")
    if any(
        "投诉" in item or "complaint" in item.lower()
        for item in (evidence or [])
    ):
        score += 0.4
        notes.append("证据中存在负面投诉")
    score = round(max(0.0, min(1.0, score)), 2)
    level = RiskLevel.LOW if score < 0.33 else RiskLevel.MEDIUM if score < 0.66 else RiskLevel.HIGH
    await monitor.report_tool_end(
        "supplier_evaluator", int((time.time() - started_at) * 1000)
    )
    return SupplierEvalOutput(
        seller=seller,
        platform=platform,
        risk_score=score,
        risk_level=level,
        notes=notes or ["暂无可用风险证据"],
    )
