"""上下文缓存管理：计算 Cache Breakpoint 并压缩早期工具结果。"""

from typing import Any


def compute_breakpoint(messages: list[Any], keep_recent: int = 3) -> int:
    """计算 Cache Breakpoint 的位置。

    保留最近 keep_recent 轮工具调用在缓存区，更早的历史进入可压缩区。
    """
    tool_call_indices = [
        i for i, msg in enumerate(messages)
        if getattr(msg, "type", None) == "tool"
    ]

    if len(tool_call_indices) <= keep_recent:
        # 工具调用不多，全部保留在缓存区
        return len(messages)

    # Breakpoint 设在"最近 K 个工具调用"的起始位置
    breakpoint_idx = tool_call_indices[-keep_recent]
    return breakpoint_idx


def compress_after_breakpoint(messages: list[Any], breakpoint_idx: int) -> list[Any]:
    """压缩 Breakpoint 之后的消息。"""
    cached_part = messages[:breakpoint_idx]  # 不动
    compressible_part = messages[breakpoint_idx:]  # 可压缩

    # 策略：把 tool_result 中超过 500 token 的内容截断
    # 这里按字符数 2000 作为近似阈值
    compressed: list[Any] = []
    for msg in compressible_part:
        content = getattr(msg, "content", "")
        if getattr(msg, "type", None) == "tool" and len(content) > 2000:
            msg = msg.copy()
            msg.content = content[:2000] + "\n[...内容已精简]"
        compressed.append(msg)

    return cached_part + compressed
