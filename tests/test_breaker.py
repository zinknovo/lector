"""熔断器状态机：连续失败打开、冷却探测、探测失败重新冷却、按会话隔离。"""

from app.agent.breaker import Permit, Refused, ToolCircuitBreaker


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock: FakeClock) -> ToolCircuitBreaker:
    return ToolCircuitBreaker(threshold=3, cooldown_seconds=60.0, clock=clock)


def _admit(
    breaker: ToolCircuitBreaker,
    session_id: str = "s1",
    tool_name: str = "web_search",
) -> Permit:
    admission = breaker.allow(session_id, tool_name)
    assert isinstance(admission, Permit)
    return admission


def test_opens_after_consecutive_failures() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)

    assert breaker.record(_admit(breaker), success=False) is None
    assert breaker.record(_admit(breaker), success=False) is None
    assert breaker.record(_admit(breaker), success=False) == "opened"

    refused = breaker.allow("s1", "web_search")
    assert isinstance(refused, Refused)
    assert 0 < refused.remaining <= 60.0


def test_success_resets_failure_streak() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    breaker.record(_admit(breaker), success=False)
    breaker.record(_admit(breaker), success=False)
    breaker.record(_admit(breaker), success=True)
    assert breaker.record(_admit(breaker), success=False) is None
    assert isinstance(breaker.allow("s1", "web_search"), Permit)


def test_probe_after_cooldown_closes_on_success() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)

    clock.advance(61)
    probe = _admit(breaker)
    assert probe.probe is True
    assert breaker.record(probe, success=True) == "closed"
    assert isinstance(breaker.allow("s1", "web_search"), Permit)


def test_probe_failure_reopens_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)
    clock.advance(61)
    probe = _admit(breaker)

    assert breaker.record(probe, success=False) == "opened"
    refused = breaker.allow("s1", "web_search")
    assert isinstance(refused, Refused)
    assert refused.remaining > 59


def test_states_are_isolated_per_session_and_tool() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)

    assert isinstance(breaker.allow("s2", "web_search"), Permit)
    assert isinstance(breaker.allow("s1", "item_search"), Permit)


def test_reset_clears_session_states() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)
    breaker.reset("s1")
    assert isinstance(breaker.allow("s1", "web_search"), Permit)


def test_second_caller_during_probe_is_refused() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)
    clock.advance(61)
    probe = _admit(breaker)
    assert probe.probe is True

    refused = breaker.allow("s1", "web_search")
    assert isinstance(refused, Refused)
    assert refused.remaining == 0.0

    # 状态未变：原探测仍然有效，成功仍能关闭熔断器
    assert breaker.record(probe, success=True) == "closed"


def test_stale_success_cannot_close_a_reopened_circuit() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    stale = _admit(breaker)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)

    assert breaker.record(stale, success=True) is None

    refused = breaker.allow("s1", "web_search")
    assert isinstance(refused, Refused)
    assert refused.remaining > 0


def test_stale_failure_cannot_restart_a_reopened_circuit() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    stale = _admit(breaker)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)

    clock.advance(10)
    assert breaker.record(stale, success=False) is None

    refused = breaker.allow("s1", "web_search")
    assert isinstance(refused, Refused)
    assert 0 < refused.remaining <= 50.0  # 冷却未被过期失败记录重置


def test_release_frees_probe_slot_and_restarts_cooldown() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)
    clock.advance(61)
    probe = _admit(breaker)
    assert probe.probe is True

    breaker.release(probe)
    breaker.release(probe)  # 幂等

    refused = breaker.allow("s1", "web_search")
    assert isinstance(refused, Refused)
    assert refused.remaining > 0

    clock.advance(61)
    next_probe = _admit(breaker)
    assert next_probe.probe is True


def test_released_probe_cannot_settle_the_next_probe() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)
    clock.advance(61)
    abandoned = _admit(breaker)
    breaker.release(abandoned)

    clock.advance(61)
    replacement = _admit(breaker)
    assert replacement != abandoned  # 归还后的票据不得与新探测等价

    assert breaker.record(abandoned, success=True) is None
    assert breaker.record(replacement, success=True) == "closed"


def test_duplicate_probe_record_after_close_is_ignored() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record(_admit(breaker), success=False)
    clock.advance(61)
    probe = _admit(breaker)

    assert breaker.record(probe, success=True) == "closed"
    assert breaker.record(probe, success=True) is None
    assert breaker.record(probe, success=False) is None
    assert isinstance(breaker.allow("s1", "web_search"), Permit)


def test_reset_invalidates_predated_permits() -> None:
    clock = FakeClock()
    breaker = _breaker(clock)
    stale = _admit(breaker)

    breaker.reset("s1")
    assert breaker.record(stale, success=False) is None

    # 重新建状态后，旧票据依然无法计数
    fresh = _admit(breaker)
    assert breaker.record(stale, success=False) is None
    assert breaker.record(fresh, success=False) is None
    assert breaker.record(_admit(breaker), success=False) is None
    assert breaker.record(_admit(breaker), success=False) == "opened"


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
