import asyncio

from app.tools.planner import PlannerOutput, planner


def test_planner_uses_llm_to_extract_selection_intent(monkeypatch) -> None:
    from app.tools import planner as module

    expected = PlannerOutput(
        intent="full_chain",
        needs=["筛选无线耳机"],
        platforms=["amazon"],
        priority="profit",
        category="wireless earbuds",
        target_market="US",
        target_margin=0.3,
    )

    class FakeStructuredLLM:
        messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return expected

    class FakeLLM:
        schema = None
        method = None

        def with_structured_output(self, schema, *, method):
            self.schema = schema
            self.method = method
            return structured

    structured = FakeStructuredLLM()
    llm = FakeLLM()
    monkeypatch.setattr(module, "get_llm", lambda: llm)

    result = asyncio.run(
        planner.ainvoke(
            {"query": "面向美国筛选 Amazon 无线耳机，目标毛利率 30%"}
        )
    )

    assert result == expected
    assert llm.schema is PlannerOutput
    assert llm.method == "json_mode"
    assert structured.messages is not None
    assert "JSON Schema" in structured.messages[0][1]
    assert "目标毛利率 30%" in structured.messages[1][1]
