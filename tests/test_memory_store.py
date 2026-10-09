"""偏好 Store：内存实现与 Mongo 实现的同一套语义（去重 / 冲突 / 上限 / 撤回）。"""

import asyncio
from typing import Any

import pytest

from app.memory.store import (
    MAX_PREFERENCES_PER_BUYER,
    InMemoryPreferenceStore,
    MongoPreferenceStore,
    PreferenceConflict,
    PreferenceStoreError,
)


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(spec):
            self._documents.sort(
                key=lambda doc: str(doc.get(key) or ""), reverse=direction == -1
            )
        return self

    def __iter__(self):
        return iter(self._documents)


class FakeDeleteResult:
    def __init__(self, deleted: int) -> None:
        self.deleted_count = deleted


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    def create_index(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [
                dict(document)
                for document in self.documents
                if document.get("buyer_id") == query.get("buyer_id")
            ]
        )

    def insert_one(self, document: dict[str, Any]) -> None:
        self.documents.append(dict(document))

    def delete_many(self, query: dict[str, Any]) -> FakeDeleteResult:
        before = len(self.documents)

        def matches(document: dict[str, Any]) -> bool:
            for key, value in query.items():
                if document.get(key) != value:
                    return False
            return True

        self.documents = [
            document for document in self.documents if not matches(document)
        ]
        return FakeDeleteResult(before - len(self.documents))


@pytest.fixture(params=["memory", "mongo"])
def store(request):
    if request.param == "memory":
        return InMemoryPreferenceStore()
    return MongoPreferenceStore(collection=FakeCollection())


def test_add_list_and_dedupe(store) -> None:
    async def run():
        first = await store.add("u1", kind="like", statement="默认做美国站")
        again = await store.add("u1", kind="like", statement=" 默认做美国站 ")
        others = await store.list_by_buyer("u2")
        return first, again, others

    first, again, others = asyncio.run(run())
    assert first.created is True
    assert again.created is False
    assert again.preference.memory_id == first.preference.memory_id
    assert others == []


def test_opposite_statement_raises_conflict(store) -> None:
    async def run():
        await store.add("u1", kind="like", statement="用塑料材质")
        await store.add("u1", kind="dislike", statement="用塑料材质")

    with pytest.raises(PreferenceConflict, match="相反偏好"):
        asyncio.run(run())


def test_limit_and_forget(store) -> None:
    async def run():
        for index in range(MAX_PREFERENCES_PER_BUYER):
            await store.add("u1", kind="like", statement=f"偏好 {index}")
        with pytest.raises(PreferenceStoreError, match="上限"):
            await store.add("u1", kind="like", statement="再来一条")
        removed = await store.forget("u1", statement="偏好 0")
        after = await store.list_by_buyer("u1")
        missing = await store.forget("u1", statement="不存在")
        return removed, after, missing

    removed, after, missing = asyncio.run(run())
    assert removed is True
    assert len(after) == MAX_PREFERENCES_PER_BUYER - 1
    assert missing is False


def test_mongo_read_failure_degrades_to_empty(monkeypatch) -> None:
    from pymongo.errors import PyMongoError

    class BrokenCollection(FakeCollection):
        def find(self, query: dict[str, Any]) -> FakeCursor:
            raise PyMongoError("boom")

    store = MongoPreferenceStore(collection=BrokenCollection())
    assert asyncio.run(store.list_by_buyer("u1")) == []


def test_mongo_write_failure_raises_store_error() -> None:
    from pymongo.errors import PyMongoError

    class BrokenCollection(FakeCollection):
        def insert_one(self, document: dict[str, Any]) -> None:
            raise PyMongoError("boom")

    store = MongoPreferenceStore(collection=BrokenCollection())

    async def run():
        await store.add("u1", kind="like", statement="默认做美国站")

    with pytest.raises(PreferenceStoreError, match="未保存"):
        asyncio.run(run())
