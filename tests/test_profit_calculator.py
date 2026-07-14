import asyncio

from app.tools.profit_calculator import ProfitCalcOutput, profit_calculator


def test_profit_calculator_computes_cny_metrics() -> None:
    result: ProfitCalcOutput = asyncio.run(
        profit_calculator.ainvoke(
            {
                "selling_price": 100.0,
                "procurement_cost": 40.0,
                "shipping_cost": 10.0,
                "platform_fee_rate": 0.15,
            }
        )
    )
    assert result.selling_price_cny == 100.0
    assert result.total_cost_cny == 65.0
    assert result.net_profit_cny == 35.0
    assert result.profit_margin_cny == 0.35


def test_profit_calculator_accepts_independent_currencies(monkeypatch) -> None:
    async def fake_rate(source_currency: str, target_currency: str = "CNY") -> float:
        return {"USD": 7.0, "CNY": 1.0}[source_currency]

    monkeypatch.setattr("app.tools.profit_calculator._rate_to_cny", fake_rate)
    result = asyncio.run(
        profit_calculator.ainvoke(
            {
                "selling_price": 20,
                "selling_currency": "USD",
                "procurement_cost": 50,
                "procurement_currency": "CNY",
                "shipping_cost": 10,
                "shipping_currency": "CNY",
                "platform_fee_rate": 0.1,
            }
        )
    )
    assert result.selling_price_cny == 140.0
    assert result.net_profit_cny == 66.0
