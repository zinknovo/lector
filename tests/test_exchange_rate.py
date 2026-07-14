import asyncio

from app.tools.exchange_rate import exchange_rate


def test_exchange_rate_identity_does_not_require_network() -> None:
    result = asyncio.run(
        exchange_rate.ainvoke({"source_currency": "CNY", "target_currency": "CNY"})
    )
    assert result.rate == 1.0
