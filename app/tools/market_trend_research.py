"""Structured market trend research for category discovery."""

import json
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.api.monitor import monitor
from app.tools.web_search import web_search


class MarketTrendOutput(BaseModel):
    category: str
    demand_score: float = Field(ge=0, le=1)
    trend_summary: str
    opportunity_gaps: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


def _fallback(category: str, evidence: str) -> MarketTrendOutput:
    usable = evidence and "占位结果" not in evidence
    summary = (
        f"已检索 {category} 的市场信号，但当前无法完成模型结构化分析。"
        if usable
        else f"{category} 暂无已接入的实时趋势数据，当前结果仅用于流程演示。"
    )
    return MarketTrendOutput(
        category=category,
        demand_score=0.5,
        trend_summary=summary,
        opportunity_gaps=[],
        keywords=[category],
    )


@tool
async def market_trend_research(category: str) -> MarketTrendOutput:
    """Research demand and opportunity gaps for an ecommerce category."""
    await monitor.report_tool_start("market_trend_research", {"category": category})
    started_at = time.time()
    evidence = str(
        await web_search.ainvoke({"query": f"{category} market trend demand 2026"})
    )
    result = _fallback(category, evidence)
    if "占位结果" not in evidence:
        try:
            response = await get_llm().ainvoke(
                [
                    (
                        "system",
                        "Return JSON with demand_score, trend_summary, opportunity_gaps, keywords.",
                    ),
                    ("user", f"Category: {category}\nEvidence:\n{evidence[:4000]}"),
                ]
            )
            content = response.content if isinstance(response.content, str) else str(response.content)
            parsed = json.loads(content)
            result = MarketTrendOutput(category=category, **parsed)
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
            pass
    await monitor.report_tool_end(
        "market_trend_research", int((time.time() - started_at) * 1000)
    )
    return result
