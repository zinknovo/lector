import asyncio
import json
import os

os.environ.setdefault("OPENSEARCH_HOST", "localhost")
os.environ.setdefault("OPENSEARCH_USER", "test")
os.environ.setdefault("OPENSEARCH_PASS", "test")
os.environ.setdefault("TOWER_USER_ENDPOINT", "http://localhost/user")
os.environ.setdefault("TOWER_QUERY_ENDPOINT", "http://localhost/query")

from langchain_core.messages import AIMessage

from app.tools.item_picker import PickedItem


def test_shopping_summary_calls_llm_and_returns_structured_output(monkeypatch) -> None:
    from app.tools import shopping_summary as module

    class FakeLLM:
        messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return AIMessage(content="最终推荐")

    fake = FakeLLM()
    monkeypatch.setattr(module, "get_llm", lambda: fake)

    pick = PickedItem(
        item_id="S1",
        platform="shopee",
        landed_cny=199,
        score=1.0,
        reasons=["价格合适"],
        flags=[],
    )

    async def run():
        return await module.shopping_summary.ainvoke(
            {
                "picks": [pick.model_dump()],
                "user_query": "找一个旅行背包",
                "new_preferences": None,
            }
        )

    result = asyncio.run(run())

    assert result.final_text == "最终推荐"
    assert result.picks == [pick]
    assert result.learned_preferences == []
    assert len(result.report) == 1
    assert result.report[0].product_id == "S1"
    assert result.report[0].risks == []
    assert fake.messages[0][0] == "system"
    payload = json.loads(fake.messages[1][1])
    assert payload["user_query"] == "找一个旅行背包"
    assert payload["picks"] == [pick.model_dump()]
