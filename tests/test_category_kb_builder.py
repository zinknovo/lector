import asyncio
import json
from pathlib import Path

from app.recall.category_kb import CategoryCard
from scripts.build_category_kb import build_category_kb


class FakeStore:
    def __init__(self) -> None:
        self.cards: list[CategoryCard] = []
        self.calls = 0

    async def upsert_many(self, cards: list[CategoryCard]) -> int:
        self.calls += 1
        self.cards.extend(cards)
        return len(cards)


def _valid_card(card_id: str, category: str = "马克杯") -> dict:
    return {
        "card_id": card_id,
        "category": category,
        "card_type": "bestseller",
        "summary": f"{category}: 陶瓷杯 / 保温杯",
        "raw_evidence": ["Model A | 99 | strong reviews"],
        "last_updated": "2026-07-14T00:00:00Z",
        "confidence": 0.9,
    }


def _write_lines(tmp_path: Path, lines: list[str]) -> Path:
    cards_path = tmp_path / "cards.jsonl"
    cards_path.write_text("\n".join(lines), encoding="utf-8")
    return cards_path


def test_builder_validates_normalizes_and_upserts_cards(tmp_path: Path) -> None:
    valid = _valid_card("card-1")
    low_confidence = {**_valid_card("card-2"), "confidence": 0.1}
    cards_path = _write_lines(
        tmp_path,
        [json.dumps(valid), json.dumps(low_confidence), "not-json", "[]", ""],
    )
    store = FakeStore()

    result = asyncio.run(build_category_kb(cards_path, store))

    assert result.model_dump() == {"read": 4, "written": 1, "rejected": 3}
    assert store.calls == 1
    assert store.cards[0].category == "咖啡杯"


def test_builder_batches_all_accepted_cards_into_one_upsert(tmp_path: Path) -> None:
    valid_cards = [_valid_card("card-1"), _valid_card("card-2", "咖啡杯")]
    cards_path = _write_lines(
        tmp_path,
        [json.dumps(card) for card in valid_cards],
    )
    store = FakeStore()

    result = asyncio.run(build_category_kb(cards_path, store))

    assert result.model_dump() == {"read": 2, "written": 2, "rejected": 0}
    assert store.calls == 1
    assert [card.card_id for card in store.cards] == ["card-1", "card-2"]


def test_builder_rejects_missing_input_file(tmp_path: Path) -> None:
    store = FakeStore()

    try:
        asyncio.run(build_category_kb(tmp_path / "missing.jsonl", store))
    except FileNotFoundError as exc:
        assert "missing.jsonl" in str(exc)
    else:
        raise AssertionError("missing input must fail")

    assert store.calls == 0
