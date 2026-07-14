"""Planner tool: decompose product-selection intent into structured fields."""

import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.agent.prompts import get_planner_prompt
from app.api.monitor import monitor


class PlannerOutput(BaseModel):
    """Structured product-selection intent extracted from the user query."""

    intent: Literal["discover", "filter", "full_chain"]
    needs: list[str]
    platforms: list[str]
    priority: str
    target_market: str | None = None
    category: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    budget_currency: str | None = None
    target_margin: float | None = Field(default=None, ge=0, le=1)
    logistics_requirements: list[str] = Field(default_factory=list)
    risk_preferences: list[str] = Field(default_factory=list)
    hard_constraints: list[str] = Field(default_factory=list)


@tool
async def planner(query: str) -> PlannerOutput:
    """把用户选品意图拆解成可执行的三阶段任务。

    Args:
        query: 用户原始选品意图。

    Returns:
        PlannerOutput: 只包含用户输入中可验证的结构化约束。
    """
    await monitor.report_tool_start("planner", {"query": query})
    started_at = time.time()
    structured_llm = get_llm().with_structured_output(
        PlannerOutput,
        method="json_mode",
    )
    response = await structured_llm.ainvoke(
        [
            (
                "system",
                f"{get_planner_prompt()}\n\nJSON Schema:\n"
                f"{PlannerOutput.model_json_schema()}",
            ),
            ("user", query),
        ]
    )
    output = PlannerOutput.model_validate(response)
    await monitor.report_tool_end(
        "planner", int((time.time() - started_at) * 1000)
    )
    return output
