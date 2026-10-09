"""按会话 + 工具的最小熔断器（连续失败计数版，教程 16-5）。

- 连续失败 ``threshold`` 次 → Open：冷却期内直接拒绝，不浪费一次完整超时；
- 冷却结束后放行**一次**半开探测：成功 → Closed；失败 → 重新冷却；
- 状态按 (会话, 工具) 隔离，单进程内存；参数可用环境变量覆盖。

状态生命周期与中间件实例绑定：一次任务新建一个中间件，新任务从不背旧任务的账。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

DEFAULT_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 60.0


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None
    probing: bool = False


class ToolCircuitBreaker:
    """连续失败即暂停调用；冷却后用一次探测决定恢复或继续冷却。"""

    def __init__(
        self,
        *,
        threshold: int | None = None,
        cooldown_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold or int(
            _env_float("LECTOR_BREAKER_THRESHOLD", DEFAULT_THRESHOLD)
        )
        self.cooldown_seconds = (
            cooldown_seconds
            if cooldown_seconds is not None
            else _env_float("LECTOR_BREAKER_COOLDOWN_SEC", DEFAULT_COOLDOWN_SECONDS)
        )
        self._clock = clock
        self._states: dict[tuple[str, str], _CircuitState] = {}

    def allow(self, session_id: str, tool_name: str) -> tuple[bool, float]:
        """返回 (是否放行, 冷却剩余秒数)。冷却结束放行一次半开探测。"""
        state = self._states.get((session_id, tool_name))
        if state is None or state.opened_at is None:
            return True, 0.0
        elapsed = self._clock() - state.opened_at
        remaining = self.cooldown_seconds - elapsed
        if remaining > 0:
            return False, remaining
        state.probing = True
        return True, 0.0

    def record(
        self, session_id: str, tool_name: str, *, success: bool
    ) -> str | None:
        """记录一次调用结果；状态变化时返回 ``"opened"`` 或 ``"closed"``。"""
        key = (session_id, tool_name)
        state = self._states.setdefault(key, _CircuitState())
        if success:
            was_paused = state.opened_at is not None or state.probing
            self._states.pop(key, None)
            return "closed" if was_paused else None
        state.failures += 1
        if state.probing:
            state.opened_at = self._clock()
            state.probing = False
            return "opened"
        if state.failures >= self.threshold and state.opened_at is None:
            state.opened_at = self._clock()
            return "opened"
        return None

    def reset(self, session_id: str) -> None:
        for key in [key for key in self._states if key[0] == session_id]:
            self._states.pop(key, None)
