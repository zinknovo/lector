import asyncio

from langchain_core.messages import HumanMessage, ToolMessage

from app.agent import middleware
from app.agent.middleware import (
    MAX_TOOL_RESULT_TOKENS,
    LoopDetector,
    post_step_compress,
    truncate_long_tool_result,
)


def test_tool_result_at_cap_is_unchanged() -> None:
    text = "x" * (MAX_TOOL_RESULT_TOKENS * 4)
    assert truncate_long_tool_result(text) == text


def test_long_tool_result_is_truncated_with_notice() -> None:
    cap = MAX_TOOL_RESULT_TOKENS * 4
    result = truncate_long_tool_result("x" * (cap + 1))

    assert "工具结果过长已截断" in result
    assert len(result) <= cap


def test_loop_detector_uses_sliding_window() -> None:
    detector = LoopDetector(window=6, repeat_threshold=4)

    assert detector.record("search") is False
    assert detector.record("search") is False
    assert detector.record("other") is False
    assert detector.record("search") is False
    assert detector.record("search") is True

    for name in ("a", "b", "c", "d"):
        detector.record(name)

    assert detector.record("search") is False


def test_post_step_compress_replaces_old_messages_and_keeps_recent(monkeypatch) -> None:
    messages = [
        HumanMessage(content="缓存前缀"),
        ToolMessage(content="x" * 2500, tool_call_id="call-1"),
        HumanMessage(content="最近消息"),
    ]

    monkeypatch.setattr(middleware, "compute_breakpoint", lambda _messages, keep_recent: 1)

    def fake_compress(_messages, breakpoint_idx):
        assert breakpoint_idx == 1
        return [messages[0], ToolMessage(content="已压缩", tool_call_id="call-1"), messages[2]]

    monkeypatch.setattr(middleware, "compress_after_breakpoint", fake_compress)

    state = asyncio.run(post_step_compress({"messages": messages.copy()}))

    assert [message.content for message in state["messages"]] == [
        "缓存前缀",
        "已压缩",
        "最近消息",
    ]
