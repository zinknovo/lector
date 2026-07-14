import asyncio

from app.tools.supplier_evaluator import RiskLevel, supplier_evaluator


def test_supplier_evaluator_returns_risk_assessment() -> None:
    result = asyncio.run(
        supplier_evaluator.ainvoke({"seller": "Anker", "platform": "amazon"})
    )
    assert result.risk_level in set(RiskLevel)
    assert result.notes


def test_supplier_evaluator_raises_risk_for_complaints() -> None:
    result = asyncio.run(
        supplier_evaluator.ainvoke(
            {"seller": "Shop", "platform": "amazon", "evidence": ["multiple complaints"]}
        )
    )
    assert result.risk_level == RiskLevel.HIGH
