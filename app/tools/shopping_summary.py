"""Terminal tool that renders a Lector selection report."""

import json
import re
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.prompts import get_shopping_summary_prompt
from app.api.monitor import monitor
from app.evidence.models import EvidenceItem
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
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ShoppingSummaryOutput(BaseModel):
    final_text: str
    decisions: list[SelectionDecision]
    report: list[SelectionReport]
    learned_preferences: list[str]
    unverified_numbers: list[str] = Field(default_factory=list)


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
        evidence=decision.evidence,
    )


_NUMBER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(%|％|元|人民币|块)?")


def _collect_allowed_numbers(decisions: list[SelectionDecision]) -> set[float]:
    """决策与证据里出现过的全部数值，作为报告数字的对照集合。"""
    allowed: set[float] = set()
    for decision in decisions:
        for value in decision.model_dump().values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                allowed.add(float(value))
        for item in decision.evidence:
            if isinstance(item.value, (int, float)) and not isinstance(
                item.value, bool
            ):
                allowed.add(float(item.value))
    return allowed


def _find_unverified_numbers(
    text: str, allowed: set[float]
) -> list[str]:
    """核验报告文本中的金额/百分比数字是否能在决策或证据中找到对应。

    只核验带金额/百分比语义或带小数的数字，避免把序号与数量误报。
    """
    hits: list[str] = []
    for match in _NUMBER_PATTERN.finditer(text):
        raw = match.group(1)
        suffix = match.group(2) or ""
        if not suffix and "." not in raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value == 0.0:
            continue
        if any(
            abs(value - candidate) < 0.011
            or abs(value - candidate * 100) < 0.011
            for candidate in allowed
        ):
            continue
        token = f"{raw}{suffix}" if suffix else raw
        if token not in hits:
            hits.append(token)
    return hits[:10]


@tool
async def shopping_summary(
    decisions: list[SelectionDecision],
    user_query: str,
    new_preferences: list[str] | None = None,
    active_preferences: list[str] | None = None,
) -> ShoppingSummaryOutput:
    """Render final prose and structured rows from verified selection decisions.

    new_preferences：只放卖家明确要求长期记住的偏好；负向偏好以「不要/避免/避开」
    开头，其余按正向偏好保存（写入由主流程完成，本工具只回传）。

    active_preferences：本次实际用上的长期偏好（来自系统提示里的偏好条目，
    只填真正影响筛选/结论的；报告会注明，无依据不要编造）。
    """
    await monitor.report_tool_start(
        "shopping_summary", {"decisions_count": len(decisions)}
    )
    started_at = time.time()
    report = [_to_report(decision) for decision in decisions]
    unverified_numbers: list[str] = []
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
                        "active_preferences": active_preferences or [],
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
        unverified_numbers = _find_unverified_numbers(
            final_text, _collect_allowed_numbers(decisions)
        )
        if unverified_numbers:
            await monitor.report_event(
                "report_number_check",
                "报告中的部分数字未能在决策证据中找到对应",
                {"unverified": unverified_numbers},
            )
    await monitor.report_tool_end(
        "shopping_summary", int((time.time() - started_at) * 1000)
    )
    return ShoppingSummaryOutput(
        final_text=final_text,
        decisions=decisions,
        report=report,
        learned_preferences=new_preferences or [],
        unverified_numbers=unverified_numbers,
    )
