import asyncio
import json

from langchain_core.messages import AIMessage

from app.tools.selection_decision import Recommendation, SelectionDecision
from app.tools.supplier_evaluator import RiskLevel


def _decision() -> SelectionDecision:
    return SelectionDecision(
        product_id="A1",
        title="Strong Product",
        platform="amazon",
        selling_price_cny=500,
        landed_cost_cny=180,
        total_cost_cny=250,
        net_profit_cny=250,
        profit_margin=0.5,
        roi=1.0,
        supplier_risk_score=0.1,
        supplier_risk_level=RiskLevel.LOW,
        market_score=0.9,
        profit_score=1.0,
        logistics_score=0.8,
        supplier_score=0.9,
        overall_score=0.91,
        confidence=1.0,
        recommendation=Recommendation.RECOMMEND,
        reasons=["利润能力达到目标"],
        risks=[],
        missing_data=[],
    )


def test_shopping_summary_preserves_decision_evidence(monkeypatch) -> None:
    from app.tools import shopping_summary as module

    class FakeLLM:
        messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return AIMessage(content="选品报告")

    fake = FakeLLM()
    monkeypatch.setattr(module, "get_llm", lambda: fake)
    decision = _decision()
    result = asyncio.run(
        module.shopping_summary.ainvoke(
            {
                "decisions": [decision.model_dump(mode="json")],
                "user_query": "选择耳机 SKU",
            }
        )
    )
    assert result.final_text == "选品报告"
    assert result.decisions == [decision]
    assert result.report[0].net_profit_cny == 250
    assert result.report[0].supplier_risk_level == RiskLevel.LOW
    assert result.report[0].confidence == 1.0
    assert fake.messages is not None
    payload = json.loads(fake.messages[1][1])
    assert payload["decisions"][0]["profit_margin"] == 0.5
    assert payload["decisions"][0]["missing_data"] == []


def test_shopping_summary_handles_empty_decisions_without_llm(monkeypatch) -> None:
    from app.tools import shopping_summary as module

    monkeypatch.setattr(
        module,
        "get_llm",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    result = asyncio.run(
        module.shopping_summary.ainvoke(
            {"decisions": [], "user_query": "选择耳机 SKU"}
        )
    )
    assert result.decisions == []
    assert result.report == []
    assert "没有可报告" in result.final_text
