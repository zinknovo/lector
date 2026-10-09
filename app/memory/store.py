"""卖家长期偏好 Store：跨会话记住默认口径（目标市场、利润率下限、避开品类等）。

最小版（教程 06，不引入 embedding 与审批流）：

- 偏好按 ``buyer_id`` 持久化到 MongoDB；索引按 buyer_id，memory_id 唯一；
- 读失败 → 返回空并记事件；**写失败 → 抛错并记事件**（不静默丢数据）；
- 不做相关性召回（条目少，全量注入）；每买家上限 50 条；
- 冲突只按"同一句话的反向偏好"识别，不自动覆盖。
"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

from app.api.monitor import monitor

MAX_PREFERENCES_PER_BUYER = 50
PREFERENCE_COLLECTION = "buyer_preferences"

PreferenceKind = Literal["like", "dislike"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Preference(BaseModel):
    """一条跨会话偏好。"""

    memory_id: str
    buyer_id: str
    kind: PreferenceKind
    statement: str
    version: int = 1
    created_at: str
    updated_at: str
    source: str = "tool"


class PreferenceWrite(BaseModel):
    """写入结果：preference 为最终记录，created=False 表示命中重复未新增。"""

    preference: Preference
    created: bool


class PreferenceConflict(Exception):
    """与既有偏好冲突：已存在同一句话的反向偏好。"""


class PreferenceStoreError(Exception):
    """存储不可用或达到上限（写路径必须显式失败）。"""


def _normalize(statement: str) -> str:
    return " ".join(statement.strip().casefold().split())


def _resolve_add(
    existing: list[Preference],
    *,
    buyer_id: str,
    kind: PreferenceKind,
    statement: str,
    source: str,
) -> PreferenceWrite:
    """去重 / 反向冲突 / 上限判定；两种实现共用同一套语义。"""
    target = _normalize(statement)
    for item in existing:
        if _normalize(item.statement) != target:
            continue
        if item.kind != kind:
            raise PreferenceConflict(
                f"已存在相反偏好（{item.kind}）：{item.statement}；请先撤回再保存"
            )
        return PreferenceWrite(preference=item, created=False)
    if len(existing) >= MAX_PREFERENCES_PER_BUYER:
        raise PreferenceStoreError(
            f"偏好数量已达上限 {MAX_PREFERENCES_PER_BUYER}，请先撤回不再需要的条目"
        )
    now = utc_now()
    preference = Preference(
        memory_id=uuid4().hex,
        buyer_id=buyer_id,
        kind=kind,
        statement=statement.strip(),
        created_at=now,
        updated_at=now,
        source=source,
    )
    return PreferenceWrite(preference=preference, created=True)


class PreferenceStore(Protocol):
    async def list_by_buyer(self, buyer_id: str) -> list[Preference]: ...

    async def add(
        self,
        buyer_id: str,
        *,
        kind: PreferenceKind,
        statement: str,
        source: str = "tool",
    ) -> PreferenceWrite: ...

    async def forget(
        self,
        buyer_id: str,
        *,
        statement: str | None = None,
        memory_id: str | None = None,
    ) -> bool: ...


class InMemoryPreferenceStore:
    """测试与降级演示用；语义与 Mongo 实现一致。"""

    def __init__(self) -> None:
        self._items: dict[str, list[Preference]] = {}

    async def list_by_buyer(self, buyer_id: str) -> list[Preference]:
        return list(self._items.get(buyer_id, []))

    async def add(
        self,
        buyer_id: str,
        *,
        kind: PreferenceKind,
        statement: str,
        source: str = "tool",
    ) -> PreferenceWrite:
        items = self._items.setdefault(buyer_id, [])
        write = _resolve_add(
            items, buyer_id=buyer_id, kind=kind, statement=statement, source=source
        )
        if write.created:
            items.append(write.preference)
        return write

    async def forget(
        self,
        buyer_id: str,
        *,
        statement: str | None = None,
        memory_id: str | None = None,
    ) -> bool:
        items = self._items.get(buyer_id, [])
        for index, existing in enumerate(items):
            if memory_id is not None and existing.memory_id != memory_id:
                continue
            if memory_id is None:
                if statement is None or _normalize(existing.statement) != _normalize(statement):
                    continue
            items.pop(index)
            return True
        return False


class MongoPreferenceStore:
    """MongoDB 持久化实现；读降级、写报错。"""

    def __init__(
        self,
        *,
        collection: Any | None = None,
        mongodb_url: str | None = None,
        collection_name: str = PREFERENCE_COLLECTION,
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
                    self._client = MongoClient(url, serverSelectionTimeoutMS=2000)
        database = self._client.get_default_database(default="lector")
        return database[self._collection_name]

    def _ensure_indexes(self, collection: Any) -> None:
        if self._indexes_ready:
            return
        with self._index_lock:
            if self._indexes_ready:
                return
            collection.create_index(
                [("memory_id", ASCENDING)], unique=True, name="preference_memory_id_unique"
            )
            collection.create_index(
                [("buyer_id", ASCENDING)], name="preference_buyer_lookup"
            )
            self._indexes_ready = True

    def _list_sync(self, buyer_id: str) -> list[Preference]:
        collection = self._get_collection()
        self._ensure_indexes(collection)
        cursor = collection.find({"buyer_id": buyer_id}).sort(
            [("created_at", ASCENDING)]
        )
        preferences: list[Preference] = []
        for document in cursor:
            payload = dict(document)
            payload.pop("_id", None)
            preferences.append(Preference.model_validate(payload))
        return preferences

    def _add_sync(
        self, buyer_id: str, kind: PreferenceKind, statement: str, source: str
    ) -> PreferenceWrite:
        collection = self._get_collection()
        self._ensure_indexes(collection)
        existing = self._list_sync(buyer_id)
        write = _resolve_add(
            existing, buyer_id=buyer_id, kind=kind, statement=statement, source=source
        )
        if write.created:
            collection.insert_one(write.preference.model_dump(mode="json"))
        return write

    def _forget_sync(
        self, buyer_id: str, statement: str | None, memory_id: str | None
    ) -> bool:
        collection = self._get_collection()
        self._ensure_indexes(collection)
        query: dict[str, Any] = {"buyer_id": buyer_id}
        if memory_id is not None:
            query["memory_id"] = memory_id
        elif statement is not None:
            query["statement"] = statement.strip()
        else:
            return False
        result = collection.delete_many(query)
        return int(getattr(result, "deleted_count", 0)) > 0

    async def list_by_buyer(self, buyer_id: str) -> list[Preference]:
        try:
            return await asyncio.to_thread(self._list_sync, buyer_id)
        except PyMongoError as exc:
            await monitor.report_event(
                "preference_store_unavailable",
                f"偏好读取失败，按无偏好继续：{type(exc).__name__}",
                {"buyer_id": buyer_id},
            )
            return []

    async def add(
        self,
        buyer_id: str,
        *,
        kind: PreferenceKind,
        statement: str,
        source: str = "tool",
    ) -> PreferenceWrite:
        try:
            return await asyncio.to_thread(
                self._add_sync, buyer_id, kind, statement, source
            )
        except (PreferenceConflict, PreferenceStoreError):
            raise
        except PyMongoError as exc:
            await monitor.report_event(
                "preference_store_unavailable",
                f"偏好保存失败：{type(exc).__name__}",
                {"buyer_id": buyer_id},
            )
            raise PreferenceStoreError("偏好存储暂时不可用，未保存") from exc

    async def forget(
        self,
        buyer_id: str,
        *,
        statement: str | None = None,
        memory_id: str | None = None,
    ) -> bool:
        try:
            return await asyncio.to_thread(
                self._forget_sync, buyer_id, statement, memory_id
            )
        except PyMongoError as exc:
            await monitor.report_event(
                "preference_store_unavailable",
                f"偏好撤回失败：{type(exc).__name__}",
                {"buyer_id": buyer_id},
            )
            raise PreferenceStoreError("偏好存储暂时不可用，未撤回") from exc


store: PreferenceStore = MongoPreferenceStore()
