import asyncio
import os
import warnings
from decimal import Decimal

import pytest

from app.data import ApifyAmazonDataSource, MockProductDataSource, Product, get_data_source
from app.data.apify_source import DataSourceError


@pytest.fixture
def mock_source() -> MockProductDataSource:
    return MockProductDataSource()


class TestMockProductDataSource:
    def test_search_returns_all_when_empty_query(self, mock_source: MockProductDataSource) -> None:
        results = asyncio.run(mock_source.search(""))
        assert len(results) == 25

    def test_search_filters_by_query(self, mock_source: MockProductDataSource) -> None:
        results = asyncio.run(mock_source.search("earbuds"))
        assert len(results) == 1
        assert results[0].product_id == "mock-004"

    def test_search_filters_by_category(self, mock_source: MockProductDataSource) -> None:
        results = asyncio.run(mock_source.search("", category="electronics"))
        assert len(results) == 6
        assert all(p.category == "electronics" for p in results)

    def test_search_filters_by_price_range(self, mock_source: MockProductDataSource) -> None:
        results = asyncio.run(mock_source.search("", price_min=10, price_max=20))
        assert len(results) == 5
        assert all(Decimal("10") <= p.price <= Decimal("20") for p in results)

    def test_search_filters_by_rating(self, mock_source: MockProductDataSource) -> None:
        results = asyncio.run(mock_source.search("", rating_min=4.5))
        assert len(results) >= 1
        assert all(p.rating is not None and p.rating >= 4.5 for p in results)

    def test_search_combines_filters(self, mock_source: MockProductDataSource) -> None:
        results = asyncio.run(
            mock_source.search("", category="kitchen_gadgets", price_max=25, rating_min=4.4)
        )
        assert len(results) == 1
        for p in results:
            assert p.category == "kitchen_gadgets"
            assert p.price <= Decimal("25")
            assert p.rating is not None and p.rating >= 4.4

    def test_search_respects_limit(self, mock_source: MockProductDataSource) -> None:
        results = asyncio.run(mock_source.search("", limit=3))
        assert len(results) == 3

    def test_get_by_id_returns_product(self, mock_source: MockProductDataSource) -> None:
        product = asyncio.run(mock_source.get_by_id("mock-001"))
        assert product is not None
        assert product.title == "Stainless Steel Kitchen Faucet Sprayer"

    def test_get_by_id_returns_none_for_unknown(self, mock_source: MockProductDataSource) -> None:
        product = asyncio.run(mock_source.get_by_id("not-found"))
        assert product is None


class TestApifyAmazonDataSource:
    def test_init_requires_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        with pytest.raises(DataSourceError, match="APIFY_API_TOKEN"):
            ApifyAmazonDataSource()

    def test_init_accepts_token_argument(self) -> None:
        source = ApifyAmazonDataSource(api_token="fake-token")
        assert source._api_token == "fake-token"
        assert source._actor_id == ApifyAmazonDataSource.DEFAULT_ACTOR_ID

    def test_init_uses_custom_actor_id_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APIFY_API_TOKEN", "fake-token")
        monkeypatch.setenv("APIFY_AMAZON_ACTOR_ID", "custom/actor")
        source = ApifyAmazonDataSource()
        assert source._actor_id == "custom/actor"

    def test_map_apify_item_normalizes_asin_and_url(self) -> None:
        from app.data.apify_source import _map_apify_item

        item = {
            "asin": "B08N5WRWNW",
            "name": "Test Product",
            "categoryBreadcrumb": "Electronics",
            "price": 29.99,
            "url": "/dp/B08N5WRWNW",
            "thumbnail": "https://m.media-amazon.com/images/test.jpg",
            "rating": 4.5,
            "reviewCount": 123,
            "seller": "Test Seller",
            "availability": "In Stock",
        }
        product = _map_apify_item(item)
        assert product.product_id == "B08N5WRWNW"
        assert product.title == "Test Product"
        assert product.platform == "amazon"
        assert product.url == "https://www.amazon.com/dp/B08N5WRWNW"
        assert product.price == Decimal("29.99")
        assert product.rating == 4.5
        assert product.review_count == 123


class TestFactory:
    def test_use_mock_true_returns_mock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("USE_MOCK", "true")
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        source = get_data_source()
        assert isinstance(source, MockProductDataSource)

    def test_use_mock_false_with_token_returns_apify(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("USE_MOCK", "false")
        monkeypatch.setenv("APIFY_API_TOKEN", "fake-token")
        source = get_data_source()
        assert isinstance(source, ApifyAmazonDataSource)

    def test_use_mock_false_without_token_falls_back_with_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("USE_MOCK", "false")
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        with pytest.warns(UserWarning, match="falling back"):
            source = get_data_source()
        assert isinstance(source, MockProductDataSource)

    def test_unset_use_mock_with_token_returns_apify(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("USE_MOCK", raising=False)
        monkeypatch.setenv("APIFY_API_TOKEN", "fake-token")
        source = get_data_source()
        assert isinstance(source, ApifyAmazonDataSource)

    def test_unset_use_mock_without_token_returns_mock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("USE_MOCK", raising=False)
        monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
        source = get_data_source()
        assert isinstance(source, MockProductDataSource)


class TestProductModel:
    def test_category_is_normalized(self) -> None:
        product = Product(
            product_id="p1",
            title="Test",
            category="Kitchen Gadgets",
            price=Decimal("10.00"),
            platform="mock",
            url="https://example.com/p1",
        )
        assert product.category == "kitchen_gadgets"

    def test_decimal_price_avoids_float_errors(self) -> None:
        product = Product(
            product_id="p1",
            title="Test",
            category="test",
            price=Decimal("29.99"),
            platform="mock",
            url="https://example.com/p1",
        )
        assert product.price == Decimal("29.99")
