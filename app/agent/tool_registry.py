"""Central registry of tools available to agent loops."""

from app.agent.dispatch_tool import dispatch_tool
from app.agent.item_search import item_search
from app.tools.category_insight import category_insight
from app.tools.chat_fallback import chat_fallback
from app.tools.item_picker import item_picker
from app.tools.exchange_rate import exchange_rate
from app.tools.market_trend_research import market_trend_research
from app.tools.planner import planner
from app.tools.price_compare import price_compare
from app.tools.product_scraper import product_scraper
from app.tools.profit_calculator import profit_calculator
from app.tools.shipping_calc import shipping_calc
from app.tools.shopping_summary import shopping_summary
from app.tools.selection_decision import selection_decision
from app.tools.supplier_evaluator import supplier_evaluator
from app.tools.web_search import web_search


FULL_TOOL_SET = [
    planner,
    chat_fallback,
    web_search,
    market_trend_research,
    product_scraper,
    exchange_rate,
    category_insight,
    item_search,
    item_picker,
    price_compare,
    shipping_calc,
    profit_calculator,
    supplier_evaluator,
    selection_decision,
    shopping_summary,
    dispatch_tool,
]

# 终结性工具：调到这些就收敛
TERMINAL_TOOLS = {"shopping_summary", "chat_fallback"}
