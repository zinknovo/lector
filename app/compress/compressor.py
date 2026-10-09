"""Compress dynamic tool results without modifying the cached prefix."""

from collections.abc import Sequence

from langchain_core.messages import BaseMessage

# 证据保护：决策与报告依赖的工具结果不参与压缩（L2 保护集合）。
PROTECTED_TOOL_NAMES = frozenset(
    {
        "selection_decision",
        "shopping_summary",
    }
)
# 证据类工具结果放宽清理阈值（里面承载关键数字与来源）。
EVIDENCE_TOOL_NAMES = frozenset(
    {
        "procurement_quote",
        "market_price_search",
        "shipping_calc",
        "exchange_rate",
        "item_picker",
        "profit_calculator",
        "supplier_evaluator",
    }
)
DEFAULT_MAX_CHARS = 2000
EVIDENCE_MAX_CHARS = 4000


def compress_after_breakpoint(
    messages: Sequence[BaseMessage], breakpoint_idx: int
) -> list[BaseMessage]:
    """Truncate large tool results after the cache breakpoint.

    - PROTECTED_TOOL_NAMES 的结果原样保留（决策/报告必须能回看）；
    - EVIDENCE_TOOL_NAMES 使用更宽松的阈值；
    - 其余工具结果截断到 DEFAULT_MAX_CHARS。
    """
    if not 0 <= breakpoint_idx <= len(messages):
        raise ValueError("breakpoint_idx is outside the message range")

    cached_part = list(messages[:breakpoint_idx])
    compressible_part = messages[breakpoint_idx:]
    compressed: list[BaseMessage] = []

    for message in compressible_part:
        content = message.content
        if message.type != "tool" or not isinstance(content, str):
            compressed.append(message)
            continue
        name = getattr(message, "name", None) or ""
        if name in PROTECTED_TOOL_NAMES:
            compressed.append(message)
            continue
        limit = (
            EVIDENCE_MAX_CHARS if name in EVIDENCE_TOOL_NAMES else DEFAULT_MAX_CHARS
        )
        if len(content) > limit:
            copied = message.model_copy(deep=True)
            copied.content = content[:limit] + "\n[...内容已精简]"
            message = copied
        compressed.append(message)

    return cached_part + compressed
