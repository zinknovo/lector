"""任务级预算计数（教程 16-4 的简化版）：累计工具调用与结果体积，超线提示收窄范围。

单模型场景下不做四档路由：只在第一次越过预算线时注入一条收敛提示（同会话一次），
不阻断执行、不切换模型。阈值可用环境变量覆盖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_TOOL_CALL_BUDGET = 30
DEFAULT_RESULT_CHAR_BUDGET = 300_000

BUDGET_HINT = (
    "[预算提示] 本次任务的工具调用与结果体量已接近上限（已调用 {calls} 次 / "
    "累计 {chars} 字符）。请收窄后续查询范围（减少条数、限定字段、复用已有证据），"
    "把重点放在证据核对与结论上。"
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class _BudgetState:
    calls: int = 0
    chars: int = 0
    hinted: bool = False
    totals: dict[str, int] = field(default_factory=dict)


class TaskBudget:
    """按会话累计工具调用次数与结果字符数；越线提示一次。"""

    def __init__(
        self,
        *,
        tool_call_budget: int | None = None,
        result_char_budget: int | None = None,
    ) -> None:
        self.tool_call_budget = (
            tool_call_budget
            if tool_call_budget is not None
            else _env_int("LECTOR_TASK_TOOL_BUDGET", DEFAULT_TOOL_CALL_BUDGET)
        )
        self.result_char_budget = (
            result_char_budget
            if result_char_budget is not None
            else _env_int(
                "LECTOR_TASK_RESULT_CHAR_BUDGET", DEFAULT_RESULT_CHAR_BUDGET
            )
        )
        self._states: dict[str, _BudgetState] = {}

    def observe(self, session_id: str, result_chars: int) -> str | None:
        """累计一次工具结果；首次越线时返回提示，否则 None。"""
        state = self._states.setdefault(session_id, _BudgetState())
        state.calls += 1
        state.chars += max(0, result_chars)
        if state.hinted:
            return None
        if (
            state.calls >= self.tool_call_budget
            or state.chars >= self.result_char_budget
        ):
            state.hinted = True
            return BUDGET_HINT.format(calls=state.calls, chars=state.chars)
        return None

    def reset(self, session_id: str) -> None:
        self._states.pop(session_id, None)
