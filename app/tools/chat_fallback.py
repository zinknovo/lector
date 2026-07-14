"""Chat fallback tool for out-of-scope or unclear user input."""

from langchain_core.tools import tool

from app.api.monitor import monitor


@tool
async def chat_fallback(question: str) -> str:
    """当用户意图不是购物或需要澄清时，用闲聊兜底。

    Args:
        question: 用户的开放式问题或模糊输入。

    Returns:
        一段引导用户回到购物场景的回复。
    """
    await monitor.report_tool_start("chat_fallback", {"question": question})
    reply = (
        "我不太确定你想买什么，能再说具体一点吗？"
        "比如预算、用途、材质偏好，我可以帮你比价比运费。"
    )
    await monitor.report_tool_end("chat_fallback", 0)
    return reply
