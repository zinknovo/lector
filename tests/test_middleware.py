"""运行时守护基础件：体积治理、指纹循环检测、压缩钩子。"""

import asyncio
import json

from langchain_core.messages import HumanMessage, ToolMessage

from app.agent import middleware
from app.agent.middleware import (
    MAX_TOOL_RESULT_CHARS,
    LoopDetector,
    cap_tool_result,
    post_step_compress,
)


class TestCapToolResult:
    def test_at_limit_is_unchanged(self) -> None:
        text = "x" * MAX_TOOL_RESULT_CHARS
        changed, result = cap_tool_result(text)
        assert changed is False
        assert result == text

    def test_oversized_json_list_is_shrunk_but_stays_valid(self) -> None:
        payload = json.dumps(
            {"items": [{"id": i, "blob": "y" * 200} for i in range(200)]},
            ensure_ascii=False,
        )
        assert len(payload) > MAX_TOOL_RESULT_CHARS
        changed, result = cap_tool_result(payload)
        assert changed is True
        assert len(result) <= MAX_TOOL_RESULT_CHARS
        parsed = json.loads(result)
        assert len(parsed["items"]) < 200
        assert parsed["_truncated"]["items"]["total"] == 200
        assert parsed["_truncated"]["items"]["kept"] == len(parsed["items"])

    def test_oversized_plain_text_is_head_truncated_with_note(self) -> None:
        changed, result = cap_tool_result("z" * (MAX_TOOL_RESULT_CHARS + 100))
        assert changed is True
        assert len(result) <= MAX_TOOL_RESULT_CHARS
        assert "结果已截断" in result


class TestLoopDetectorFingerprint:
    def _observe(self, detector: LoopDetector, args: dict, result: str, state: str = "success"):
        return detector.observe(
            session_id="s1",
            tool_name="item_search",
            arguments=args,
            result=result,
            state=state,
        )

    def test_same_args_and_result_fires_at_threshold(self) -> None:
        detector = LoopDetector(window=6, repeat_threshold=3)
        args = {"query": "蓝牙耳机"}
        result = '{"items": [1, 2]}'
        assert self._observe(detector, args, result) is None
        assert self._observe(detector, args, result) is None
        hint = self._observe(detector, args, result)
        assert hint is not None
        assert "item_search" in hint

    def test_changed_result_is_not_a_loop(self) -> None:
        detector = LoopDetector(window=6, repeat_threshold=3)
        args = {"query": "蓝牙耳机"}
        results = ['{"items": [1]}', '{"items": [2]}', '{"items": [3]}']
        for result in results:
            assert self._observe(detector, args, result) is None

    def test_changed_args_are_not_a_loop(self) -> None:
        detector = LoopDetector(window=6, repeat_threshold=3)
        result = '{"items": [1]}'
        for i in range(3):
            assert self._observe(detector, {"query": f"蓝牙耳机{i}"}, result) is None

    def test_error_state_is_ignored(self) -> None:
        detector = LoopDetector(window=6, repeat_threshold=3)
        args = {"query": "蓝牙耳机"}
        result = "[error] 工具暂时不可用"
        for _ in range(4):
            assert self._observe(detector, args, result, state="error") is None

    def test_sessions_are_isolated(self) -> None:
        detector = LoopDetector(window=6, repeat_threshold=3)
        args = {"query": "蓝牙耳机"}
        result = '{"items": [1]}'
        detector.observe(session_id="a", tool_name="t", arguments=args, result=result)
        detector.observe(session_id="a", tool_name="t", arguments=args, result=result)
        assert (
            detector.observe(
                session_id="b", tool_name="t", arguments=args, result=result
            )
            is None
        )

    def test_reset_clears_window(self) -> None:
        detector = LoopDetector(window=6, repeat_threshold=3)
        args = {"query": "蓝牙耳机"}
        result = '{"items": [1]}'
        self._observe(detector, args, result)
        self._observe(detector, args, result)
        detector.reset("s1")
        assert self._observe(detector, args, result) is None


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
