"""Terminal tool that renders the final shopping recommendation."""

import json
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.prompts import get_shopping_summary_prompt
from app.api.monitor import monitor
from app.tools.item_picker import PickedItem


class SelectionReport(BaseModel):
    product_id: str
    title: str
    platform: str
    landed_cny: float
    profit_margin: float | None = None
    score: float
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ShoppingSummaryOutput(BaseModel):
    final_text: str
    picks: list[PickedItem]
    report: list[SelectionReport]
    learned_preferences: list[str]


@tool
async def shopping_summary(
    picks: list[PickedItem],
    user_query: str,
    new_preferences: list[str] | None = None,
) -> ShoppingSummaryOutput:
    """生成最终购物清单和选购理由。"""
    await monitor.report_tool_start(
        "shopping_summary", {"picks_count": len(picks)}
    )
    t0 = time.time()

    messages = [
        ("system", get_shopping_summary_prompt()),
        (
            "user",
            json.dumps(
                {
                    "user_query": user_query,
                    "picks": [pick.model_dump() for pick in picks],
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
        "shopping_summary", int((time.time() - t0) * 1000)
    )
    return ShoppingSummaryOutput(
        final_text=final_text,
        picks=picks,
        report=[
            SelectionReport(
                product_id=pick.item_id,
                title=pick.title or pick.item_id,
                platform=pick.platform,
                landed_cny=pick.landed_cny,
                score=pick.score,
                reasons=pick.reasons,
                risks=pick.flags,
            )
            for pick in picks
        ],
        learned_preferences=new_preferences or [],
    )
