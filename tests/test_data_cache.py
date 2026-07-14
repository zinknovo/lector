from decimal import Decimal

from app.data.cache import ProductSearchCache
from app.data.models import Product


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def create_index(self, *args, **kwargs) -> None:
        return None

    def find_one(self, query: dict) -> dict | None:
        return self.docs.get(query["_id"])

    def replace_one(self, query: dict, document: dict, upsert: bool) -> None:
        self.docs[query["_id"]] = document

    def delete_one(self, query: dict) -> None:
        self.docs.pop(query["_id"], None)


def test_cache_stores_and_retrieves_products() -> None:
    collection = FakeCollection()
    cache = ProductSearchCache(collection=collection)
    products = [
        Product(
            product_id="B123",
            title="Test",
            category="electronics",
            price=Decimal("9.99"),
            platform="amazon",
            url="https://amazon.com/dp/B123",
        )
    ]
    cache.set("amazon", "test", {"limit": 5}, products)
    result = cache.get("amazon", "test", {"limit": 5})
    assert result is not None
    assert result[0].price == Decimal("9.99")


def test_cache_key_is_stable_for_filter_order() -> None:
    first = ProductSearchCache._key("amazon", "test", {"a": 1, "b": 2})
    second = ProductSearchCache._key("amazon", "test", {"b": 2, "a": 1})
    assert first == second


def test_cache_without_connection_is_noop() -> None:
    cache = ProductSearchCache(mongodb_url=None)
    assert cache.get("amazon", "test", {}) is None
