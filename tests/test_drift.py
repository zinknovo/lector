"""漂移检测：四类规则信号、按会话隔离、每类每会话只提示一次。"""

from app.agent.drift import DriftDetector

GOAL = "帮我找蓝牙耳机，美国站上架，预算300元以内"


def _detector() -> DriftDetector:
    detector = DriftDetector()
    detector.start_turn("s1", GOAL)
    return detector


def test_constraint_drop_fires_when_destination_violates_declared_market() -> None:
    detector = _detector()
    signals = detector.observe(
        session_id="s1",
        tool_name="shipping_calc",
        arguments={"destination": "CN"},
        result_text="{}",
    )
    assert [signal.kind for signal in signals] == ["constraint_drop"]
    assert "US" in signals[0].hint or "美国" in signals[0].hint

    # 同类信号本会话不再重复提示
    again = detector.observe(
        session_id="s1",
        tool_name="shipping_calc",
        arguments={"destination": "JP"},
        result_text="{}",
    )
    assert again == []


def test_constraint_drop_for_budget() -> None:
    detector = _detector()
    signals = detector.observe(
        session_id="s1",
        tool_name="item_search",
        arguments={"query": "蓝牙耳机", "price_max_major": 500.0},
        result_text="{}",
    )
    assert any(signal.kind == "constraint_drop" for signal in signals)


def test_declared_market_compliant_call_has_no_signal() -> None:
    detector = _detector()
    signals = detector.observe(
        session_id="s1",
        tool_name="shipping_calc",
        arguments={"destination": "US"},
        result_text="{}",
    )
    assert signals == []


def test_goal_drift_fires_after_consecutive_low_overlap_queries() -> None:
    detector = _detector()
    drifted_queries = ["户外帐篷 露营装备 批发", "登山绳 攀岩装备 货源", "渔具 钓鱼竿 采购"]
    collected = []
    for query in drifted_queries:
        collected = detector.observe(
            session_id="s1",
            tool_name="item_search",
            arguments={"query": query},
            result_text='{"items": [1]}',
        )
    assert any(signal.kind == "goal_drift" for signal in collected)


def test_on_topic_queries_do_not_trigger_goal_drift() -> None:
    detector = _detector()
    for query in ("蓝牙耳机 降噪 批发", "蓝牙耳机 真无线 货源", "美国站 蓝牙耳机 选品"):
        signals = detector.observe(
            session_id="s1",
            tool_name="item_search",
            arguments={"query": query},
            result_text='{"items": [1]}',
        )
        assert all(signal.kind != "goal_drift" for signal in signals)


def test_empty_streak_fires_and_resets() -> None:
    detector = _detector()
    collected = []
    for _ in range(3):
        collected = detector.observe(
            session_id="s1",
            tool_name="item_search",
            arguments={"query": "蓝牙耳机"},
            result_text='{"items": []}',
        )
    assert any(signal.kind == "empty_streak" for signal in collected)

    detector2 = DriftDetector()
    detector2.start_turn("s1", GOAL)
    for _ in range(2):
        signals = detector2.observe(
            session_id="s1",
            tool_name="item_search",
            arguments={"query": "蓝牙耳机"},
            result_text='{"items": []}',
        )
        assert all(signal.kind != "empty_streak" for signal in signals)
    signals = detector2.observe(
        session_id="s1",
        tool_name="item_search",
        arguments={"query": "蓝牙耳机"},
        result_text='{"items": [1]}',
    )
    assert all(signal.kind != "empty_streak" for signal in signals)


def test_cost_runaway_fires_on_growing_results() -> None:
    detector = _detector()
    collected = []
    for size in (500, 600, 550, 5000, 6000, 7000):
        collected = detector.observe(
            session_id="s1",
            tool_name="web_search",
            arguments={"query": f"x{size}"},
            result_text="y" * size,
        )
    assert any(signal.kind == "cost_runaway" for signal in collected)


def test_unknown_session_produces_no_signals() -> None:
    detector = DriftDetector()
    assert (
        detector.observe(
            session_id="nope",
            tool_name="shipping_calc",
            arguments={"destination": "CN"},
            result_text="{}",
        )
        == []
    )


def test_reset_clears_session_state() -> None:
    detector = _detector()
    detector.observe(
        session_id="s1",
        tool_name="shipping_calc",
        arguments={"destination": "CN"},
        result_text="{}",
    )
    detector.reset("s1")
    signals = detector.observe(
        session_id="s1",
        tool_name="shipping_calc",
        arguments={"destination": "CN"},
        result_text="{}",
    )
    assert signals == []  # 目标已清空，不再产生信号
