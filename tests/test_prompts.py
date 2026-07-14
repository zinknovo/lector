from app.agent.prompts import get_system_prompt


def test_system_prompt_contains_terminal_and_loop_guardrails() -> None:
    prompt = get_system_prompt()

    assert "立刻调用 shopping_summary" in prompt
    assert "new_preferences" in prompt
    assert "[dispatch_tool 拒绝]" in prompt
    assert "[dispatch_tool 超时]" in prompt
    assert "重复调用 4 次" in prompt

