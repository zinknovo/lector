import asyncio

from app.agent.item_search import ItemSearchOutput, item_search


def test_item_search_returns_candidates_from_mock() -> None:
    result: ItemSearchOutput = asyncio.run(
        item_search.ainvoke(
            {"query": "camping", "platform": "mock", "top_k": 3}
        )
    )
    assert len(result.candidates) == 3
    assert all(candidate.platform == "mock" for candidate in result.candidates)


def test_item_search_carries_product_metrics() -> None:
    result: ItemSearchOutput = asyncio.run(
        item_search.ainvoke({"query": "earbuds", "platform": "mock"})
    )
    candidate = result.candidates[0]
    assert candidate.review_count == 3400
    assert candidate.sales == 5600
