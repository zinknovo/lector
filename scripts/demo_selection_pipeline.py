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
from app.tools.selection_decision import SelectionDecision, selection_decision
from app.tools.supplier_evaluator import supplier_evaluator


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
    candidate_by_id = {
        candidate.item_id: candidate for candidate in search_result.candidates
    }
    landed_by_id = {item.item_id: item for item in landed.items}
    decisions: list[SelectionDecision] = []
    for pick in picks.picks:
        candidate = candidate_by_id[pick.item_id]
        landed_item = landed_by_id[pick.item_id]
        profit = await profit_calculator.ainvoke(
            {
                "selling_price": round(pick.landed_cny * 1.8, 2),
                "procurement_cost": pick.landed_cny,
                "platform_fee_rate": 0.15,
            }
        )
        supplier = await supplier_evaluator.ainvoke(
            {
                "seller": candidate.seller or "unknown",
                "platform": candidate.platform,
            }
        )
        decision = await selection_decision.ainvoke(
            {
                "product_id": candidate.item_id,
                "title": candidate.title,
                "platform": candidate.platform,
                "rating": candidate.rating,
                "review_count": candidate.review_count,
                "sales": candidate.sales,
                "selling_price_cny": profit.selling_price_cny,
                "landed_cost_cny": landed_item.landed_cny,
                "shipping_cost_cny": landed_item.shipping_cny,
                "eta_days": landed_item.eta_days,
                "total_cost_cny": profit.total_cost_cny,
                "net_profit_cny": profit.net_profit_cny,
                "profit_margin": profit.profit_margin_cny,
                "roi": profit.roi_cny,
                "supplier_risk_score": supplier.risk_score,
                "supplier_risk_level": supplier.risk_level,
            }
        )
        decisions.append(decision)
        print(
            f"{decision.product_id}: recommendation={decision.recommendation.value}, "
            f"score={decision.overall_score:.2f}, confidence={decision.confidence:.2f}, "
            f"margin={decision.profit_margin:.2%}"
        )

    print("\n=== Report ===")
    try:
        summary = await shopping_summary.ainvoke(
            {
                "decisions": [decision.model_dump(mode="json") for decision in decisions],
                "user_query": category,
            }
        )
        print(summary.final_text)
    except Exception as exc:
        print(f"LLM 摘要不可用（{type(exc).__name__}），输出结构化结果：")
        for decision in decisions:
            print(decision.model_dump_json())


if __name__ == "__main__":
    asyncio.run(main())
