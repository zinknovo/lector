import asyncio

from app.tools.selection_decision import Recommendation, selection_decision
from app.tools.supplier_evaluator import RiskLevel


def _complete_input() -> dict[str, object]:
    return {
        "product_id": "A1",
        "title": "Strong Product",
        "platform": "amazon",
        "rating": 4.9,
        "review_count": 10000,
        "sales": 10000,
        "selling_price_cny": 500,
        "landed_cost_cny": 180,
        "shipping_cost_cny": 10,
        "eta_days": 8,
        "total_cost_cny": 250,
        "net_profit_cny": 250,
        "profit_margin": 0.5,
        "roi": 1.0,
        "supplier_risk_score": 0.1,
        "supplier_risk_level": "low",
    }


def test_complete_strong_product_is_recommended() -> None:
    result = asyncio.run(selection_decision.ainvoke(_complete_input()))
    assert result.recommendation == Recommendation.RECOMMEND
    assert result.confidence == 1.0
    assert result.overall_score >= 0.7
    assert result.missing_data == []


def test_missing_profit_and_supplier_cannot_recommend() -> None:
    payload = _complete_input()
    for key in (
        "total_cost_cny",
        "net_profit_cny",
        "profit_margin",
        "roi",
        "supplier_risk_score",
        "supplier_risk_level",
    ):
        payload.pop(key)
    result = asyncio.run(selection_decision.ainvoke(payload))
    assert result.recommendation != Recommendation.RECOMMEND
    assert result.confidence == 0.5
    assert "profit" in result.missing_data
    assert "supplier" in result.missing_data


def test_high_supplier_risk_forces_rejection() -> None:
    payload = _complete_input()
    payload["supplier_risk_score"] = 0.9
    payload["supplier_risk_level"] = RiskLevel.HIGH.value
    result = asyncio.run(selection_decision.ainvoke(payload))
    assert result.recommendation == Recommendation.REJECT
    assert any("供应商" in risk for risk in result.risks)
