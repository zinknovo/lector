from langchain_core.messages import HumanMessage, ToolMessage

from app.compress.breakpoint import compute_breakpoint
from app.compress.compressor import compress_after_breakpoint


def _tool(content: str, index: int) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=f"call-{index}")


def test_compute_breakpoint_starts_at_recent_tool_call_window() -> None:
    messages = [
        HumanMessage(content="q0"),
        _tool("r1", 1),
        HumanMessage(content="q2"),
        _tool("r3", 3),
        HumanMessage(content="q4"),
        _tool("r5", 5),
        HumanMessage(content="q6"),
        _tool("r7", 7),
    ]

    assert compute_breakpoint(messages, keep_recent=3) == 3


def test_compute_breakpoint_keeps_everything_when_tool_calls_are_few() -> None:
    messages = [HumanMessage(content="q"), _tool("r", 1)]
    assert compute_breakpoint(messages, keep_recent=3) == len(messages)


def test_compress_after_breakpoint_keeps_prefix_and_truncates_long_tool_result() -> None:
    cached = HumanMessage(content="缓存前缀")
    long_tool = _tool("x" * 2500, 1)
    short_tool = _tool("short", 2)

    result = compress_after_breakpoint(
        [cached, long_tool, short_tool], breakpoint_idx=1
    )

    assert result[0] is cached
    assert result[1] is not long_tool
    assert result[1].content == "x" * 2000 + "\n[...内容已精简]"
    assert long_tool.content == "x" * 2500
    assert result[2] is short_tool
