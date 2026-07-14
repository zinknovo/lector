"""Agent middleware for tool-output bounds, loop detection and compression."""

from collections import deque
from typing import Any

from langchain_core.messages import BaseMessage

from app.compress.breakpoint import compute_breakpoint
from app.compress.compressor import compress_after_breakpoint


MAX_TOOL_RESULT_TOKENS = 4000  # 约 16000 字符


def truncate_long_tool_result(result_text: str) -> str:
    """工具返回过长时尾部加省略提示，让模型知道有截断。"""
    cap = MAX_TOOL_RESULT_TOKENS * 4
    if len(result_text) <= cap:
        return result_text
    head = result_text[: cap - 200]
    tail = "\n\n[...工具结果过长已截断，主 loop 可调更窄的查询参数]"
    return head + tail


class LoopDetector:
    def __init__(self, window: int = 6, repeat_threshold: int = 4) -> None:
        self.window = window
        self.threshold = repeat_threshold
        self._recent: deque[str] = deque(maxlen=window)

    def record(self, tool_name: str) -> bool:
        """记录一次工具调用，返回 True 表示触发了循环。"""
        self._recent.append(tool_name)
        return self._recent.count(tool_name) >= self.threshold


async def post_step_compress(state: dict[str, Any]) -> dict[str, Any]:
    """每轮 Act 后压缩动态区，同时保持缓存前缀不变。"""
    messages = state["messages"]
    if not isinstance(messages, list):
        return state

    breakpoint = compute_breakpoint(messages, keep_recent=3)
    if breakpoint == len(messages):
        return state

    typed_messages = [
        message for message in messages if isinstance(message, BaseMessage)
    ]
    if len(typed_messages) != len(messages):
        return state

    state["messages"] = compress_after_breakpoint(
        typed_messages, breakpoint_idx=breakpoint
    )
    return state
