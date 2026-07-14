"""品类知识存储接口及 MongoDB 实现。"""

import asyncio
import os
import threading
from functools import lru_cache
from typing import Any, Literal, Protocol

from pymongo import ASCENDING, DESCENDING, MongoClient, ReplaceOne

from app.recall.category_kb import CategoryCard
from app.recall.category_norm import normalize_category

CategoryCardType = Literal["bestseller", "attribute", "price_range"]


class CategoryKnowledgeStore(Protocol):
    """品类知识存储后端的最小接口。"""

    async def search(
        self,
        category: str,
        *,
        card_types: set[CategoryCardType] | None = None,
        limit: int = 8,
    ) -> list[CategoryCard]: ...

    async def upsert_many(self, cards: list[CategoryCard]) -> int: ...


class MongoCategoryKnowledgeStore:
    """使用结构化精确查询的 MongoDB 品类知识存储。"""

    def __init__(
        self,
        *,
        collection: Any | None = None,
        mongodb_url: str | None = None,
        collection_name: str = "category_cards",
    ) -> None:
        self._collection_override = collection
        self._mongodb_url = mongodb_url
        self._collection_name = collection_name
        self._client: MongoClient[dict[str, Any]] | None = None
        self._indexes_ready = False
        self._resource_lock = threading.Lock()
        self._index_lock = threading.Lock()

    def _get_collection(self) -> Any:
        if self._collection_override is not None:
            return self._collection_override
        if self._client is None:
            with self._resource_lock:
                if self._client is None:
                    url = self._mongodb_url or os.environ.get(
                        "MONGODB_URL", "mongodb://localhost:27017/lector"
                    )
                    self._client = MongoClient(url)
        database = self._client.get_default_database(default="lector")
        return database[self._collection_name]

    def _ensure_indexes(self, collection: Any) -> None:
        if self._indexes_ready:
            return
        with self._index_lock:
            if self._indexes_ready:
                return
            collection.create_index(
                [("card_id", ASCENDING)],
                unique=True,
                name="category_card_id_unique",
            )
            collection.create_index(
                [
                    ("category", ASCENDING),
                    ("card_type", ASCENDING),
                    ("confidence", DESCENDING),
                ],
                name="category_lookup",
            )
            self._indexes_ready = True

    def _search_sync(
        self,
        category: str,
        card_types: set[CategoryCardType] | None,
        limit: int,
    ) -> list[CategoryCard]:
        collection = self._get_collection()
        self._ensure_indexes(collection)
        query: dict[str, Any] = {
            "category": normalize_category(category),
            "confidence": {"$gte": 0.5},
        }
        if card_types:
            query["card_type"] = {"$in": sorted(card_types)}
        cursor = collection.find(query).sort(
            [
                ("confidence", DESCENDING),
                ("last_updated", DESCENDING),
                ("card_id", ASCENDING),
            ]
        ).limit(limit)
        cards: list[CategoryCard] = []
        for document in cursor:
            payload = dict(document)
            payload.pop("_id", None)
            cards.append(CategoryCard.model_validate(payload))
        return cards

    async def search(
        self,
        category: str,
        *,
        card_types: set[CategoryCardType] | None = None,
        limit: int = 8,
    ) -> list[CategoryCard]:
        if limit <= 0:
            return []
        return await asyncio.to_thread(
            self._search_sync,
            category,
            card_types,
            limit,
        )

    def _upsert_many_sync(self, cards: list[CategoryCard]) -> int:
        collection = self._get_collection()
        self._ensure_indexes(collection)
        operations: list[ReplaceOne] = []
        for card in cards:
            normalized = card.model_copy(
                update={"category": normalize_category(card.category)}
            )
            document = normalized.model_dump(mode="json")
            operations.append(
                ReplaceOne(
                    {"card_id": normalized.card_id},
                    document,
                    upsert=True,
                )
            )
        collection.bulk_write(operations, ordered=False)
        return len(cards)

    async def upsert_many(self, cards: list[CategoryCard]) -> int:
        if not cards:
            return 0
        return await asyncio.to_thread(self._upsert_many_sync, cards)


@lru_cache(maxsize=1)
def get_category_knowledge_store() -> CategoryKnowledgeStore:
    """返回进程内复用的默认品类知识存储。"""
    return MongoCategoryKnowledgeStore()
