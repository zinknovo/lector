import asyncio
from unittest.mock import AsyncMock

import pytest

from app.recall.category_kb import CategoryCard
from app.tools import category_insight as module


def _card(
    card_id: str,
    card_type: str,
    summary: str,
    raw_evidence: list[str] | None = None,
) -> CategoryCard:
    return CategoryCard.model_validate(
        {
            "card_id": card_id,
            "category": "咖啡杯",
            "card_type": card_type,
            "summary": summary,
            "raw_evidence": raw_evidence or [],
            "last_updated": "2026-07-14T00:00:00Z",
            "confidence": 0.8,
        }
    )


CARDS = [
    _card(
        "best-1",
        "bestseller",
        "咖啡杯: 陶瓷杯 / 保温杯",
        ["Model A | 99 | strong reviews"],
    ),
    _card("attr-1", "attribute", "材质: 塑料 60% / 金属 40%"),
    _card("price-1", "price_range", "便宜款 50-100"),
]


class FakeStore:
    def __init__(
        self,
        cards: list[CategoryCard],
        error: Exception | None = None,
    ) -> None:
        self.cards = cards
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, category: str, *, card_types=None, limit: int = 8):
        self.calls.append((category, limit))
        if self.error is not None:
            raise self.error
        return self.cards


def _patch_monitor(monkeypatch) -> None:
    monkeypatch.setattr(module.monitor, "report_tool_start", AsyncMock())
    monkeypatch.setattr(module.monitor, "report_tool_end", AsyncMock())
    monkeypatch.setattr(module.monitor, "report_error", AsyncMock())


def test_category_insight_uses_store_and_preserves_deep_output(monkeypatch) -> None:
    store = FakeStore(CARDS)
    monkeypatch.setattr(module, "get_category_knowledge_store", lambda: store)
    _patch_monitor(monkeypatch)

    result = asyncio.run(
        module.category_insight.ainvoke({"category": " 马克杯 ", "depth": "deep"})
    )

    assert store.calls == [("咖啡杯", 15)]
    assert result.category == "咖啡杯"
    assert result.components == ["保温杯", "陶瓷杯"]
    assert result.bestsellers[0].name == "Model A"
    assert result.attributes[0].distribution == {"塑料": 0.6, "金属": 0.4}
    assert result.price_tiers[0].range_cny == (50.0, 100.0)
    assert result.confidence == 0.8


def test_quick_category_insight_omits_attributes(monkeypatch) -> None:
    store = FakeStore(CARDS)
    monkeypatch.setattr(module, "get_category_knowledge_store", lambda: store)
    _patch_monitor(monkeypatch)

    result = asyncio.run(module.category_insight.ainvoke({"category": "马克杯"}))

    assert store.calls == [("咖啡杯", 8)]
    assert result.attributes == []


def test_empty_category_insight_is_a_normal_zero_confidence_result(monkeypatch) -> None:
    store = FakeStore([])
    monkeypatch.setattr(module, "get_category_knowledge_store", lambda: store)
    _patch_monitor(monkeypatch)

    result = asyncio.run(module.category_insight.ainvoke({"category": "马克杯"}))

    assert result.confidence == 0.0
    assert result.bestsellers == []
    module.monitor.report_error.assert_not_awaited()
    module.monitor.report_tool_end.assert_awaited_once()


def test_category_insight_reports_and_reraises_store_error(monkeypatch) -> None:
    store = FakeStore([], RuntimeError("mongo unavailable"))
    monkeypatch.setattr(module, "get_category_knowledge_store", lambda: store)
    _patch_monitor(monkeypatch)

    with pytest.raises(RuntimeError, match="mongo unavailable"):
        asyncio.run(module.category_insight.ainvoke({"category": "马克杯"}))

    module.monitor.report_error.assert_awaited_once_with(
        "RuntimeError",
        "category_insight failed: mongo unavailable",
    )
    module.monitor.report_tool_end.assert_not_awaited()
