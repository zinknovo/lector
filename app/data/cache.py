"""MongoDB-backed cache for normalized product searches."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.data.models import Product


class ProductSearchCache:
    def __init__(
        self,
        mongodb_url: str | None = None,
        db_name: str = "lector",
        collection_name: str = "product_search_cache",
        ttl_days: int = 7,
        collection: Any | None = None,
    ) -> None:
        self._mongodb_url = mongodb_url or os.environ.get("MONGODB_URL")
        self._db_name = db_name
        self._collection_name = collection_name
        self._ttl_days = ttl_days
        self._collection = collection
        self._initialized = collection is not None

    @staticmethod
    def _key(source: str, query: str, filters: dict[str, Any]) -> str:
        payload = json.dumps(
            {"source": source, "query": query, "filters": filters},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_collection(self) -> Any | None:
        if self._initialized:
            return self._collection
        self._initialized = True
        if not self._mongodb_url:
            return None
        try:
            from pymongo import ASCENDING, MongoClient

            client = MongoClient(
                self._mongodb_url,
                serverSelectionTimeoutMS=500,
                connectTimeoutMS=500,
            )
            collection = client[self._db_name][self._collection_name]
            if self._ttl_days > 0:
                collection.create_index(
                    [("created_at", ASCENDING)],
                    expireAfterSeconds=self._ttl_days * 86400,
                )
            self._collection = collection
        except Exception:
            self._collection = None
        return self._collection

    def get(
        self, source: str, query: str, filters: dict[str, Any]
    ) -> list[Product] | None:
        collection = self._get_collection()
        if collection is None:
            return None
        try:
            key = self._key(source, query, filters)
            document = collection.find_one({"_id": key})
            if document is None:
                return None
            created_at = document.get("created_at")
            if isinstance(created_at, datetime) and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if (
                self._ttl_days > 0
                and created_at
                and datetime.now(timezone.utc) - created_at
                >= timedelta(days=self._ttl_days)
            ):
                collection.delete_one({"_id": key})
                return None
            return [Product.model_validate(item) for item in document["products"]]
        except Exception:
            return None

    def set(
        self,
        source: str,
        query: str,
        filters: dict[str, Any],
        products: list[Product],
    ) -> None:
        collection = self._get_collection()
        if collection is None:
            return
        try:
            key = self._key(source, query, filters)
            collection.replace_one(
                {"_id": key},
                {
                    "_id": key,
                    "source": source,
                    "query": query,
                    "filters": filters,
                    "products": [p.model_dump(mode="json") for p in products],
                    "created_at": datetime.now(timezone.utc),
                },
                upsert=True,
            )
        except Exception:
            return
