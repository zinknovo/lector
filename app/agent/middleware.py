"""Agent 运行时守护的基础件：工具结果治理、循环检测与压缩。

- ``cap_tool_result``：工具结果进入上下文前的体积治理（L0）。结构化 JSON
  优先按列表字段裁剪并留下 ``_truncated`` 说明（保持 JSON 合法）；无法
  结构化处理时退回“头部 + 截断说明”。
- ``LoopDetector``：按会话比较“工具 + 参数 + 完整结果”指纹；同参同果重复
  达到阈值时返回一条收敛提示（只提示，不强制终止）。
- ``post_step_compress``：保持缓存前缀不变的前提下压缩旧工具结果；由
  ``HarnessMiddleware`` 在模型调用前调用（见 app/agent/harness.py）。
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any, Mapping

from langchain_core.messages import BaseMessage

from app.compress.breakpoint import compute_breakpoint
from app.compress.compressor import compress_after_breakpoint


MAX_TOOL_RESULT_TOKENS = 4000  # 约 16000 字符
MAX_TOOL_RESULT_CHARS = MAX_TOOL_RESULT_TOKENS * 4

# 结构化裁剪时优先处理的列表字段（工具输出里的“条目集合”）
_LIST_FIELDS = (
    "items",
    "results",
    "candidates",
    "picks",
    "evidence",
    "hits",
    "cards",
    "products",
    "prices",
)

_TRUNCATION_NOTE = (
    "[结果已截断：本次返回超过体积上限；完整明细请按条目重新查询或缩小查询范围]"
)


def _shrink_json_lists(data: dict[str, Any], limit: int) -> bool:
    """按列表字段裁剪 JSON（保持结构合法），返回是否发生改动。"""
    changed = False
    for key in _LIST_FIELDS:
        value = data.get(key)
        if not isinstance(value, list) or len(value) <= 3:
            continue
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        if len(encoded) <= limit // 2:
            continue
        total = len(value)
        keep = max(2, total // 2)
        while keep > 2 and len(
            json.dumps(value[:keep], ensure_ascii=False, default=str)
        ) > limit // 2:
            keep //= 2
        data[key] = value[:keep]
        truncated = data.get("_truncated")
        if not isinstance(truncated, dict):
            truncated = {}
            data["_truncated"] = truncated
        truncated[key] = {
            "kept": keep,
            "total": total,
            "note": _TRUNCATION_NOTE,
        }
        changed = True
    return changed


def cap_tool_result(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> tuple[bool, str]:
    """工具结果体积治理：结构化裁剪优先，超限退回头部截断。

    Returns:
        (是否发生截断, 处理后的文本)。
    """
    if len(text) <= limit:
        return False, text
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict) and _shrink_json_lists(parsed, limit):
        encoded = json.dumps(parsed, ensure_ascii=False, default=str)
        if len(encoded) <= limit:
            return True, encoded
        text = encoded
    head = text[: max(0, limit - len(_TRUNCATION_NOTE) - 2)]
    return True, f"{head}\n{_TRUNCATION_NOTE}"


CONVERGE_HINT = (
    "检测到 {tool} 已连续 {count} 次以相同参数得到相同结果，任务没有推进。"
    "请不要重复同一动作：改用不同关键词或参数，或基于已有证据直接给出结论；"
    "确实拿不到数据时如实说明缺口。"
)


def _canonical(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


def _fingerprint(
    tool_name: str, arguments: Mapping[str, Any], result: Any
) -> str:
    payload = json.dumps(
        {
            "tool": tool_name,
            "args": _canonical(dict(arguments)),
            "result": _canonical(result),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LoopDetector:
    """按会话记录“同工具、同参数、同结果”的重复取证；只提示不终止。"""

    def __init__(self, window: int = 6, repeat_threshold: int = 3) -> None:
        if repeat_threshold < 1:
            raise ValueError("repeat_threshold 必须为正")
        if window < repeat_threshold:
            raise ValueError("window 必须不小于 repeat_threshold")
        self.window = window
        self.threshold = repeat_threshold
        self._recent: dict[str, deque[tuple[str, str]]] = {}

    def observe(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        result: Any,
        state: str = "success",
    ) -> str | None:
        """记录一次已完成调用；命中阈值时返回收敛提示。"""
        if state != "success":
            return None
        fingerprint = _fingerprint(tool_name, arguments, result)
        window = self._recent.setdefault(
            session_id, deque(maxlen=self.window)
        )
        window.append((tool_name, fingerprint))
        count = sum(
            1 for name, fp in window if name == tool_name and fp == fingerprint
        )
        if count >= self.threshold and count % self.threshold == 0:
            return CONVERGE_HINT.format(tool=tool_name, count=count)
        return None

    def reset(self, session_id: str) -> None:
        self._recent.pop(session_id, None)


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
