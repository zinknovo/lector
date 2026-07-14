import ast
from pathlib import Path


def test_full_tool_set_registers_all_implemented_tools() -> None:
    source = Path("app/agent/tool_registry.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    registered: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "FULL_TOOL_SET"
            for target in node.targets
        ):
            assert isinstance(node.value, ast.List)
            registered = {
                element.id
                for element in node.value.elts
                if isinstance(element, ast.Name)
            }

    assert registered == {
        "planner",
        "chat_fallback",
        "web_search",
        "market_trend_research",
        "product_scraper",
        "exchange_rate",
        "item_search",
        "category_insight",
        "item_picker",
        "price_compare",
        "shipping_calc",
        "profit_calculator",
        "supplier_evaluator",
        "shopping_summary",
        "dispatch_tool",
    }
