"""按会话 + 工具的最小熔断器（许可票据版，教程 16-5）。

- 连续失败 ``threshold`` 次 → Open：冷却期内直接拒绝，不浪费一次完整超时；
- 冷却结束后放行**一次**半开探测：成功 → Closed；失败 → 重新冷却；
- 状态按 (会话, 工具) 隔离，单进程内存；参数可用环境变量覆盖。

每次放行都带一张 ``Permit``，记录结果时必须交回同一张票据。票据上的 ``epoch``
标识放行时状态所处的代次：熔断器一旦切换状态（打开、关闭、归还探测、重置），
代次递增，旧票据的结果随即失效，不会把重新打开的熔断器又推回 Closed。

状态生命周期与中间件实例绑定：一次任务新建一个中间件，新任务从不背旧任务的账。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Literal

from app.utils.env import env_float

DEFAULT_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 60.0


@dataclass(frozen=True)
class Permit:
    """一次被放行的调用；epoch 是放行时熔断器所处的代次。"""

    session_id: str
    tool_name: str
    epoch: int
    probe: bool = False


@dataclass(frozen=True)
class Refused:
    """拒绝放行；remaining 为 0 表示冷却已过但探测名额仍被占用。"""

    remaining: float


Admission = Permit | Refused


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None
    epoch: int = 0
    probe: Permit | None = None


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
            env_float("LECTOR_BREAKER_THRESHOLD", DEFAULT_THRESHOLD)
        )
        self.cooldown_seconds = (
            cooldown_seconds
            if cooldown_seconds is not None
            else env_float("LECTOR_BREAKER_COOLDOWN_SEC", DEFAULT_COOLDOWN_SECONDS)
        )
        self._clock = clock
        self._states: dict[tuple[str, str], _CircuitState] = {}
        self._epoch = 0

    def _next_epoch(self) -> int:
        """推进全局代次，让此前发出的票据全部失去效力。"""
        self._epoch += 1
        return self._epoch

    def allow(self, session_id: str, tool_name: str) -> Admission:
        """放行一次调用并返回票据；冷却期内或探测名额被占用时返回拒绝。"""
        key = (session_id, tool_name)
        state = self._states.get(key)
        if state is None:
            state = _CircuitState(epoch=self._epoch)
            self._states[key] = state
        if state.opened_at is None:
            return Permit(session_id, tool_name, state.epoch)
        remaining = self.cooldown_seconds - (self._clock() - state.opened_at)
        if remaining > 0:
            return Refused(remaining)
        if state.probe is not None:
            return Refused(0.0)
        permit = Permit(session_id, tool_name, state.epoch, probe=True)
        state.probe = permit
        return permit

    def record(
        self, permit: Permit, *, success: bool
    ) -> Literal["opened", "closed"] | None:
        """记录一次调用结果；状态变化时返回 ``"opened"`` 或 ``"closed"``。"""
        state = self._states.get((permit.session_id, permit.tool_name))
        if state is None or permit.epoch != state.epoch:
            return None
        if state.opened_at is None:
            if success:
                state.failures = 0
                return None
            state.failures += 1
            if state.failures >= self.threshold:
                self._open(state)
                return "opened"
            return None
        if state.probe != permit:
            return None
        if success:
            state.probe = None
            state.failures = 0
            state.opened_at = None
            state.epoch = self._next_epoch()
            return "closed"
        self._open(state)
        return "opened"

    def _open(self, state: _CircuitState) -> None:
        """切到 Open：清空探测名额，从此刻重新计时，并作废在飞结果。"""
        state.probe = None
        state.opened_at = self._clock()
        state.epoch = self._next_epoch()

    def release(self, permit: Permit) -> None:
        """归还探测名额；探测被放弃时从现在重新计时，避免立即重试。"""
        state = self._states.get((permit.session_id, permit.tool_name))
        if state is None:
            return
        if state.epoch == permit.epoch and state.probe == permit:
            state.probe = None
            state.opened_at = self._clock()
            state.epoch = self._next_epoch()

    def reset(self, session_id: str) -> None:
        """丢弃该会话的全部状态，并让此前发出的票据无法再匹配。"""
        for key in [key for key in self._states if key[0] == session_id]:
            self._states.pop(key, None)
        self._next_epoch()
