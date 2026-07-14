import ast
from pathlib import Path


def test_main_agent_is_built_with_limits_tools_and_compression_hook() -> None:
    source = Path("app/agent/main_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "MAIN_AGENT_MAX_ITERATIONS = 30" in source
    assert "MAIN_AGENT_TIMEOUT_SEC = 300" in source
    assert "tools=FULL_TOOL_SET" in source
    assert "pre_model_hook=post_step_compress" in source
    assert any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "run_agent"
        for node in ast.walk(tree)
    )
