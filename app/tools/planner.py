"""Planner tool: decompose user shopping intent into structured fields."""

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor


class PlannerOutput(BaseModel):
    """结构化购物意图。"""

    needs: list[str]
    platforms: list[str]
    priority: str


@tool
async def planner(query: str) -> PlannerOutput:
    """把用户购物意图拆解成可执行子任务。

    Args:
        query: 用户原始购物意图，如 "便宜又抗造的旅行三件套"。

    Returns:
        needs: 子需求列表。
        platforms: 建议检索的平台列表。
        priority: 决策优先级，如 price / quality / speed。
    """
    await monitor.report_tool_start("planner", {"query": query})

    # TODO: replace with LLM-based planning
    output = PlannerOutput(
        needs=[query],
        platforms=["amazon", "shopee", "aliexpress", "ebay"],
        priority="price",
    )

    await monitor.report_tool_end("planner", 0)
    return output
