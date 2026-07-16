from app.agent.prompts import (
    get_planner_prompt,
    get_shopping_summary_prompt,
    get_system_prompt,
)


def test_system_prompt_contains_terminal_and_loop_guardrails() -> None:
    prompt = get_system_prompt()

    assert "立刻调用 shopping_summary" in prompt
    assert "new_preferences" in prompt
    assert "[dispatch_tool 拒绝]" in prompt
    assert "[dispatch_tool 超时]" in prompt
    assert "重复调用 4 次" in prompt
    assert "Lector" in prompt
    assert "discover" in prompt
    assert "filter" in prompt
    assert "full_chain" in prompt
    assert "profit_calculator" in prompt
    assert "procurement_quote" in prompt
    assert "supplier_evaluator" in prompt
    assert "selection_decision" in prompt
    assert "SelectionDecision" in prompt
    assert "Globex" not in prompt
    assert "中国货源" in prompt
    assert "destination=US" in prompt
    assert "海淘代购" in prompt


def test_selection_prompts_prohibit_invented_metrics() -> None:
    assert "discover | filter | full_chain" in get_planner_prompt()
    summary = get_shopping_summary_prompt()
    assert "不得补写" in summary
    assert "SelectionDecision" in summary
