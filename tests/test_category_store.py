import asyncio
from typing import Any

from app.recall.category_kb import CategoryCard
from app.recall.category_store import MongoCategoryKnowledgeStore


CARD_DOCUMENT = {
    "card_id": "card-1",
    "category": "咖啡杯",
    "card_type": "bestseller",
    "summary": "咖啡杯: 陶瓷杯 / 保温杯",
    "raw_evidence": ["Model A | 99 | strong reviews"],
    "last_updated": "2026-07-14T00:00:00Z",
    "confidence": 0.9,
}


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.sort_spec: list[tuple[str, int]] | None = None
        self.limit_value: int | None = None

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        self.sort_spec = spec
        return self

    def limit(self, value: int) -> "FakeCursor":
        self.limit_value = value
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.last_filter: dict[str, Any] | None = None
        self.cursor: FakeCursor | None = None
        self.indexes: list[tuple[Any, dict[str, Any]]] = []
        self.operations: list[Any] = []

    def create_index(self, keys: Any, **kwargs: Any) -> None:
        self.indexes.append((keys, kwargs))

    def find(self, query: dict[str, Any]) -> FakeCursor:
        self.last_filter = query
        self.cursor = FakeCursor(self.documents)
        return self.cursor

    def bulk_write(self, operations: list[Any], *, ordered: bool) -> None:
        assert ordered is False
        self.operations = operations


def _card(**updates: Any) -> CategoryCard:
    return CategoryCard.model_validate({**CARD_DOCUMENT, **updates})


def test_search_normalizes_filters_sorts_and_limits() -> None:
    collection = FakeCollection([{**CARD_DOCUMENT, "_id": "mongo-id"}])
    store = MongoCategoryKnowledgeStore(collection=collection)

    cards = asyncio.run(
        store.search(" 马克杯 ", card_types={"bestseller"}, limit=3)
    )

    assert collection.last_filter == {
        "category": "咖啡杯",
        "card_type": {"$in": ["bestseller"]},
        "confidence": {"$gte": 0.5},
    }
    assert collection.cursor is not None
    assert collection.cursor.sort_spec == [
        ("confidence", -1),
        ("last_updated", -1),
        ("card_id", 1),
    ]
    assert collection.cursor.limit_value == 3
    assert cards == [CategoryCard.model_validate(CARD_DOCUMENT)]


def test_search_with_non_positive_limit_does_not_query() -> None:
    collection = FakeCollection([CARD_DOCUMENT])
    store = MongoCategoryKnowledgeStore(collection=collection)

    assert asyncio.run(store.search("咖啡杯", limit=0)) == []
    assert collection.last_filter is None


def test_upsert_many_creates_indexes_and_normalizes_documents() -> None:
    collection = FakeCollection([])
    store = MongoCategoryKnowledgeStore(collection=collection)

    written = asyncio.run(
        store.upsert_many([_card(category=" 马克杯 ")])
    )

    assert written == 1
    assert collection.indexes == [
        ([('card_id', 1)], {"unique": True, "name": "category_card_id_unique"}),
        (
            [("category", 1), ("card_type", 1), ("confidence", -1)],
            {"name": "category_lookup"},
        ),
    ]
    operation = collection.operations[0]
    assert operation._filter == {"card_id": "card-1"}
    assert operation._doc["category"] == "咖啡杯"
    assert operation._upsert is True


def test_empty_upsert_does_not_create_indexes_or_write() -> None:
    collection = FakeCollection([])
    store = MongoCategoryKnowledgeStore(collection=collection)

    assert asyncio.run(store.upsert_many([])) == 0
    assert collection.indexes == []
    assert collection.operations == []
