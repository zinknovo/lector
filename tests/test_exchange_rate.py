import asyncio

from app.tools.exchange_rate import exchange_rate
from app.tools.web_search import WebSearchOutput


def test_exchange_rate_identity_does_not_require_network() -> None:
    result = asyncio.run(
        exchange_rate.ainvoke({"source_currency": "CNY", "target_currency": "CNY"})
    )
    assert result.rate == 1.0


def test_exchange_rate_refuses_to_guess_without_search_evidence(monkeypatch) -> None:
    from app.tools import exchange_rate as module

    class FakeSearch:
        async def ainvoke(self, payload):
            return WebSearchOutput(
                query=payload["query"],
                status="unavailable",
                error="not configured",
            )

    monkeypatch.setattr(module, "web_search", FakeSearch())
    monkeypatch.setattr(
        module,
        "get_llm",
        lambda: (_ for _ in ()).throw(AssertionError("LLM must not guess")),
    )
    module._CACHE.clear()
    try:
        asyncio.run(
            module.exchange_rate.ainvoke(
                {"source_currency": "USD", "target_currency": "CNY"}
            )
        )
    except RuntimeError as exc:
        assert "实时汇率" in str(exc)
    else:
        raise AssertionError("Expected unavailable live rate")
