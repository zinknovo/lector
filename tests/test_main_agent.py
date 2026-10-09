import ast
from pathlib import Path


def test_main_agent_is_built_with_limits_tools_and_harness_middleware() -> None:
    source = Path("app/agent/main_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "MAIN_AGENT_MAX_ITERATIONS = 45" in source
    assert "MAIN_AGENT_TIMEOUT_SEC" in source
    assert "tools=FULL_TOOL_SET" in source
    assert "middleware=[build_harness_middleware()]" in source
    assert "checkpointer=checkpointer" in source
    assert "open_checkpointer(session_dir)" in source
    assert "audit_output" in source
    assert any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "run_agent"
        for node in ast.walk(tree)
    )


def test_extract_learned_preferences_from_summary_tool_message() -> None:
    import json

    from langchain_core.messages import AIMessage, ToolMessage

    from app.agent.main_agent import extract_learned_preferences

    messages = [
        AIMessage(content="done"),
        ToolMessage(
            content=json.dumps(
                {"learned_preferences": ["默认做美国站", " 避免塑料 "]},
                ensure_ascii=False,
            ),
            tool_call_id="c1",
            name="shopping_summary",
        ),
    ]
    assert extract_learned_preferences(messages) == ["默认做美国站", "避免塑料"]
    assert extract_learned_preferences([AIMessage(content="no tool result")]) == []


def test_infer_preference_kind_uses_dislike_prefixes() -> None:
    from app.agent.main_agent import infer_preference_kind

    assert infer_preference_kind("避免塑料材质") == "dislike"
    assert infer_preference_kind("不要塑料") == "dislike"
    assert infer_preference_kind("默认做美国站") == "like"


def test_persist_learned_preferences_writes_with_inferred_kind(monkeypatch) -> None:
    import asyncio
    import json

    from langchain_core.messages import ToolMessage

    from app.agent import main_agent
    from app.memory.store import InMemoryPreferenceStore

    store = InMemoryPreferenceStore()
    monkeypatch.setattr(main_agent, "store", store)
    messages = [
        ToolMessage(
            content=json.dumps(
                {"learned_preferences": ["默认做美国站", "避免塑料"]},
                ensure_ascii=False,
            ),
            tool_call_id="c1",
            name="shopping_summary",
        )
    ]

    asyncio.run(main_agent.persist_learned_preferences("u1", messages))

    saved = asyncio.run(store.list_by_buyer("u1"))
    assert [(item.kind, item.statement) for item in saved] == [
        ("like", "默认做美国站"),
        ("dislike", "避免塑料"),
    ]
