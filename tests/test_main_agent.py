import ast
from pathlib import Path


def test_main_agent_is_built_with_limits_tools_and_harness_middleware() -> None:
    source = Path("app/agent/main_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "MAIN_AGENT_MAX_ITERATIONS = 45" in source
    assert "MAIN_AGENT_TIMEOUT_SEC" in source
    assert "tools=FULL_TOOL_SET" in source
    assert "middleware=[build_harness_middleware()]" in source
    assert "audit_output" in source
    assert any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "run_agent"
        for node in ast.walk(tree)
    )
