"""运行时守护中间件：工具边界与轮次边界的护栏。

对应教程 17-2 的 Hook 生命周期，用 LangChain 原生 ``AgentMiddleware`` 实现：

- ``wrap_tool_call``（工具返回后）：L3 注入过滤 → L0 体积治理 → 循环检测
  → 漂移观察；命中只记事件并排队一条提示，不改写本轮回复。
- ``before_model``（模型调用前）：压缩旧工具结果（保持缓存前缀）并在末尾
  注入上一轮排队的漂移/收敛提示。
- ``before_agent``：登记本轮选品目标（漂移检测的比较基准）。
"""

from __future__ import annotations

import os
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agent.drift import DriftDetector
from app.agent.middleware import LoopDetector, cap_tool_result, post_step_compress
from app.api.context import get_thread_id
from app.api.monitor import monitor
from app.security.guards import sanitize_tool_output

_DEFAULT_SESSION = "default"


def drift_enabled() -> bool:
    """规则漂移检测默认开启；``LECTOR_DRIFT_DETECT=0`` 可关闭。"""
    return os.environ.get("LECTOR_DRIFT_DETECT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


def _replace_message_text(message: ToolMessage, text: str) -> ToolMessage:
    content = message.content
    if isinstance(content, list):
        rebuilt: list[Any] = []
        replaced = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                if replaced:
                    continue  # 文本块已合并进第一个块
                rebuilt.append({**block, "text": text})
                replaced = True
            else:
                rebuilt.append(block)
        return message.model_copy(update={"content": rebuilt})
    return message.model_copy(update={"content": text})


class HarnessMiddleware(AgentMiddleware):
    """工具结果与轮次边界的统一护栏；按会话隔离状态。"""

    def __init__(
        self,
        *,
        enable_drift: bool = True,
        enable_content_filter: bool = True,
        loop_detector: LoopDetector | None = None,
        drift_detector: DriftDetector | None = None,
    ) -> None:
        super().__init__()
        self._enable_drift = enable_drift
        self._enable_content_filter = enable_content_filter
        self._loop = loop_detector or LoopDetector()
        self._drift = drift_detector or DriftDetector()
        self._pending_hints: dict[str, list[str]] = {}

    # -- 工具返回后 -------------------------------------------------------

    def _queue_hint(self, session_id: str, hint: str) -> None:
        self._pending_hints.setdefault(session_id, []).append(hint)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        tool_name = str(request.tool_call.get("name", ""))
        arguments = request.tool_call.get("args", {})
        session_id = get_thread_id() or _DEFAULT_SESSION
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result

        text = _message_text(result.content)
        original = text

        if self._enable_content_filter:
            hit, text = sanitize_tool_output(text)
            if hit:
                await monitor.report_event(
                    "injection_filtered",
                    f"{tool_name} 的返回命中疑似注入模式，已就地过滤",
                    {"tool": tool_name, "session": session_id},
                )

        capped, text = cap_tool_result(text)
        if capped:
            await monitor.report_event(
                "tool_result_capped",
                f"{tool_name} 的返回过大，已裁剪后进入上下文",
                {"tool": tool_name, "before": len(original), "after": len(text)},
            )

        hint = self._loop.observe(
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments if isinstance(arguments, dict) else {},
            result=text,
        )
        if hint:
            self._queue_hint(session_id, hint)
            await monitor.report_event(
                "loop_detected",
                f"{tool_name} 重复调用且没有推进，已注入收敛提示",
                {"tool": tool_name, "session": session_id},
            )

        if self._enable_drift:
            for signal in self._drift.observe(
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments if isinstance(arguments, dict) else {},
                result_text=text,
            ):
                self._queue_hint(session_id, signal.hint)
                await monitor.report_event(
                    "drift_signal",
                    signal.hint,
                    {"kind": signal.kind, "detail": signal.detail, "tool": tool_name},
                )

        if text != original:
            return _replace_message_text(result, text)
        return result

    # -- 模型调用前 -------------------------------------------------------

    async def abefore_model(
        self, state: Any, runtime: Any
    ) -> dict[str, Any] | None:
        session_id = get_thread_id() or _DEFAULT_SESSION
        messages = list(state["messages"])

        compressed_state = await post_step_compress({"messages": messages})
        new_messages = compressed_state["messages"]

        hints = self._pending_hints.pop(session_id, [])
        if hints:
            new_messages = [
                *new_messages,
                *(SystemMessage(content=hint) for hint in hints),
            ]

        if len(new_messages) == len(messages) and all(
            new is old for new, old in zip(new_messages, messages)
        ):
            return None
        return {"messages": new_messages}

    # -- 会话开始 ---------------------------------------------------------

    async def abefore_agent(
        self, state: Any, runtime: Any
    ) -> dict[str, Any] | None:
        if not self._enable_drift:
            return None
        session_id = get_thread_id() or _DEFAULT_SESSION
        goal: str | None = None
        for message in state.get("messages", []):
            if isinstance(message, HumanMessage):
                goal = _message_text(message.content)
                break
        if goal:
            self._drift.reset(session_id)
            self._drift.start_turn(session_id, goal)
            self._loop.reset(session_id)
        return None


def build_harness_middleware(*, enable_drift: bool = True) -> HarnessMiddleware:
    """构建护栏中间件；子 Agent 传 ``enable_drift=False``（各自没有选品目标）。"""
    return HarnessMiddleware(enable_drift=enable_drift and drift_enabled())
