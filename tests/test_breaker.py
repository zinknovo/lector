"""熔断器状态机：连续失败打开、冷却探测、探测失败重新冷却、按会话隔离。"""

from app.agent.breaker import ToolCircuitBreaker


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock: FakeClock) -> ToolCircuitBreaker:
    return ToolCircuitBreaker(threshold=3, cooldown_seconds=60.0, clock=clock)


def test_opens_after_consecutive_failures() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)

    assert breaker.record("s1", "web_search", success=False) is None
    assert breaker.record("s1", "web_search", success=False) is None
    assert breaker.record("s1", "web_search", success=False) == "opened"

    allowed, remaining = breaker.allow("s1", "web_search")
    assert allowed is False
    assert 0 < remaining <= 60.0


def test_success_resets_failure_streak() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    breaker.record("s1", "web_search", success=False)
    breaker.record("s1", "web_search", success=False)
    breaker.record("s1", "web_search", success=True)
    assert breaker.record("s1", "web_search", success=False) is None
    assert breaker.allow("s1", "web_search") == (True, 0.0)


def test_probe_after_cooldown_closes_on_success() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record("s1", "web_search", success=False)

    clock.advance(61)
    allowed, _ = breaker.allow("s1", "web_search")
    assert allowed is True  # 半开探测
    assert breaker.record("s1", "web_search", success=True) == "closed"
    assert breaker.allow("s1", "web_search") == (True, 0.0)


def test_probe_failure_reopens_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record("s1", "web_search", success=False)
    clock.advance(61)
    breaker.allow("s1", "web_search")  # 取得探测资格

    assert breaker.record("s1", "web_search", success=False) == "opened"
    allowed, remaining = breaker.allow("s1", "web_search")
    assert allowed is False
    assert remaining > 59  # 冷却重新开始


def test_states_are_isolated_per_session_and_tool() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record("s1", "web_search", success=False)

    assert breaker.allow("s2", "web_search") == (True, 0.0)
    assert breaker.allow("s1", "item_search") == (True, 0.0)


def test_reset_clears_session_states() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record("s1", "web_search", success=False)
    breaker.reset("s1")
    assert breaker.allow("s1", "web_search") == (True, 0.0)


class TestTaskBudget:
    def test_hint_fires_once_on_call_budget(self) -> None:
        from app.agent.budget import TaskBudget

        budget = TaskBudget(tool_call_budget=2, result_char_budget=10**9)
        assert budget.observe("s1", 10) is None
        hint = budget.observe("s1", 10)
        assert hint is not None and "预算提示" in hint
        assert budget.observe("s1", 10) is None  # 只提示一次

    def test_hint_fires_on_char_budget(self) -> None:
        from app.agent.budget import TaskBudget

        budget = TaskBudget(tool_call_budget=10**6, result_char_budget=100)
        hint = budget.observe("s1", 120)
        assert hint is not None

    def test_sessions_are_isolated_and_reset_clears(self) -> None:
        from app.agent.budget import TaskBudget

        budget = TaskBudget(tool_call_budget=1, result_char_budget=10**9)
        assert budget.observe("s1", 1) is not None
        assert budget.observe("s2", 1) is not None
        budget.reset("s1")
        assert budget.observe("s1", 1) is not None
