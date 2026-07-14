"""Compress dynamic tool results without modifying the cached prefix."""

from collections.abc import Sequence

from langchain_core.messages import BaseMessage


def compress_after_breakpoint(
    messages: Sequence[BaseMessage], breakpoint_idx: int
) -> list[BaseMessage]:
    """Truncate large tool results after the cache breakpoint."""
    if not 0 <= breakpoint_idx <= len(messages):
        raise ValueError("breakpoint_idx is outside the message range")

    cached_part = list(messages[:breakpoint_idx])
    compressible_part = messages[breakpoint_idx:]
    compressed: list[BaseMessage] = []

    for message in compressible_part:
        content = message.content
        if message.type == "tool" and isinstance(content, str) and len(content) > 2000:
            copied = message.model_copy(deep=True)
            copied.content = content[:2000] + "\n[...内容已精简]"
            message = copied
        compressed.append(message)

    return cached_part + compressed
