"""Demo: discover category -> filter products -> make selection decisions."""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
os.environ.setdefault("OPENSEARCH_HOST", "localhost")
os.environ.setdefault("OPENSEARCH_USER", "demo")
os.environ.setdefault("OPENSEARCH_PASS", "demo")
os.environ.setdefault("TOWER_USER_ENDPOINT", "http://localhost/user")
os.environ.setdefault("TOWER_QUERY_ENDPOINT", "http://localhost/query")

from app.agent.item_search import item_search
from app.tools.item_picker import item_picker
from app.tools.market_trend_research import market_trend_research
from app.tools.price_compare import price_compare
from app.tools.profit_calculator import profit_calculator
from app.tools.shipping_calc import shipping_calc
from app.tools.shopping_summary import shopping_summary


async def main() -> None:
    category = "wireless earbuds"
    print("=== Stage 1: Discover ===")
    trend = await market_trend_research.ainvoke({"category": category})
    print(trend.trend_summary)

    print("\n=== Stage 2: Filter ===")
    search_result = await item_search.ainvoke(
        {"query": "earbuds", "platform": "mock", "top_k": 5, "rating_min": 4.0}
    )
    compare = await price_compare.ainvoke(
        {"candidates": [c.model_dump() for c in search_result.candidates], "top_n": 3}
    )
    landed = await shipping_calc.ainvoke(
        {"points": [p.model_dump() for p in compare.ranked], "destination": "CN"}
    )
    picks = await item_picker.ainvoke(
        {"landed": [item.model_dump() for item in landed.items], "top_n": 2}
    )
    print(f"候选 {len(search_result.candidates)} 件，入选 {len(picks.picks)} 件")

    print("\n=== Stage 3: Decide ===")
    for pick in picks.picks:
        profit = await profit_calculator.ainvoke(
            {
                "selling_price": round(pick.landed_cny * 1.3, 2),
                "procurement_cost": pick.landed_cny,
                "platform_fee_rate": 0.15,
            }
        )
        print(
            f"{pick.item_id}: score={pick.score}, "
            f"margin={profit.profit_margin_cny:.2%}, "
            f"net_profit_cny={profit.net_profit_cny:.2f}"
        )

    print("\n=== Report ===")
    try:
        summary = await shopping_summary.ainvoke(
            {"picks": [p.model_dump() for p in picks.picks], "user_query": category}
        )
        print(summary.final_text)
    except Exception as exc:
        print(f"LLM 摘要不可用（{type(exc).__name__}），输出结构化结果：")
        for pick in picks.picks:
            print(pick.model_dump_json())


if __name__ == "__main__":
    asyncio.run(main())
