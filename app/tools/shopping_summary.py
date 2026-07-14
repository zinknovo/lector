"""Terminal tool that renders a Lector selection report."""

import json
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.prompts import get_shopping_summary_prompt
from app.api.monitor import monitor
from app.tools.selection_decision import Recommendation, SelectionDecision
from app.tools.supplier_evaluator import RiskLevel


class SelectionReport(BaseModel):
    product_id: str
    title: str
    platform: str
    recommendation: Recommendation
    selling_price_cny: float | None = None
    landed_cost_cny: float | None = None
    total_cost_cny: float | None = None
    net_profit_cny: float | None = None
    profit_margin: float | None = None
    roi: float | None = None
    supplier_risk_score: float | None = None
    supplier_risk_level: RiskLevel | None = None
    overall_score: float
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)


class ShoppingSummaryOutput(BaseModel):
    final_text: str
    decisions: list[SelectionDecision]
    report: list[SelectionReport]
    learned_preferences: list[str]


def _to_report(decision: SelectionDecision) -> SelectionReport:
    return SelectionReport(
        product_id=decision.product_id,
        title=decision.title,
        platform=decision.platform,
        recommendation=decision.recommendation,
        selling_price_cny=decision.selling_price_cny,
        landed_cost_cny=decision.landed_cost_cny,
        total_cost_cny=decision.total_cost_cny,
        net_profit_cny=decision.net_profit_cny,
        profit_margin=decision.profit_margin,
        roi=decision.roi,
        supplier_risk_score=decision.supplier_risk_score,
        supplier_risk_level=decision.supplier_risk_level,
        overall_score=decision.overall_score,
        confidence=decision.confidence,
        reasons=decision.reasons,
        risks=decision.risks,
        missing_data=decision.missing_data,
    )


@tool
async def shopping_summary(
    decisions: list[SelectionDecision],
    user_query: str,
    new_preferences: list[str] | None = None,
) -> ShoppingSummaryOutput:
    """Render final prose and structured rows from verified selection decisions."""
    await monitor.report_tool_start(
        "shopping_summary", {"decisions_count": len(decisions)}
    )
    started_at = time.time()
    report = [_to_report(decision) for decision in decisions]
    if not decisions:
        final_text = "没有可报告的选品决策；请先完成商品筛选和决策聚合。"
    else:
        messages = [
            ("system", get_shopping_summary_prompt()),
            (
                "user",
                json.dumps(
                    {
                        "user_query": user_query,
                        "decisions": [
                            decision.model_dump(mode="json") for decision in decisions
                        ],
                    },
                    ensure_ascii=False,
                ),
            ),
        ]
        response = await get_llm().ainvoke(messages)
        content = response.content
        final_text = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False, default=str)
        )
    await monitor.report_tool_end(
        "shopping_summary", int((time.time() - started_at) * 1000)
    )
    return ShoppingSummaryOutput(
        final_text=final_text,
        decisions=decisions,
        report=report,
        learned_preferences=new_preferences or [],
    )
