"""Web search tool for reviews, trends and external references."""

from langchain_core.tools import tool

from app.api.monitor import monitor


@tool
async def web_search(query: str) -> str:
    """通用网络搜索，用于查评测、博主推荐、价格趋势等。

    Args:
        query: 搜索关键词。

    Returns:
        搜索结果摘要（当前为占位实现）。
    """
    await monitor.report_tool_start("web_search", {"query": query})

    # TODO: integrate real web search API
    result = f"[web_search 占位结果] {query}：未接入真实搜索，请先配置搜索 API。"

    await monitor.report_tool_end("web_search", 0)
    return result
