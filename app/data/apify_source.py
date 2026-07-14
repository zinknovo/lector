"""Apify Amazon Scraper product data source."""

import os
from decimal import Decimal
from typing import Any

from app.data.base import ProductDataSource
from app.data.cache import ProductSearchCache
from app.data.models import Product


class DataSourceError(Exception):
    """Raised when a data source fails to fetch or parse products."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause

    def __str__(self) -> str:
        if self.cause is not None:
            return f"{self.message}: {type(self.cause).__name__}: {self.cause}"
        return self.message


class ApifyAmazonDataSource(ProductDataSource):
    """Fetch products from Amazon via the Apify Amazon Scraper Actor."""

    # Note: Actor names are case-sensitive. This public scraper supports
    # searchQueries input and returns results quickly.
    DEFAULT_ACTOR_ID = "automation-lab/amazon-scraper"

    def __init__(
        self,
        api_token: str | None = None,
        actor_id: str | None = None,
        cache: ProductSearchCache | None = None,
    ) -> None:
        self._api_token = api_token or os.environ.get("APIFY_API_TOKEN")
        if not self._api_token:
            raise DataSourceError(
                "ApifyAmazonDataSource requires an APIFY_API_TOKEN environment variable or api_token argument."
            )
        self._actor_id = actor_id or os.environ.get(
            "APIFY_AMAZON_ACTOR_ID", self.DEFAULT_ACTOR_ID
        )
        self._cache = cache or ProductSearchCache()

    async def search(self, query: str, **filters) -> list[Product]:
        """Search Amazon for products matching the query.

        The query is passed to the Actor as a search term. Optional filters
        are applied to the returned items.
        """
        cache_filters = dict(filters)
        cached = self._cache.get(self._actor_id, query, cache_filters)
        if cached is not None:
            return _apply_filters(cached, filters)

        try:
            from apify_client import ApifyClient
        except ImportError as exc:
            raise DataSourceError(
                "apify-client is not installed; run `uv sync` to install it."
            ) from exc

        client = ApifyClient(self._api_token)
        max_results = filters.get("max_results", 20)
        run_input: dict[str, Any] = {
            "searchQueries": [query],
            "marketplace": filters.get("marketplace", "US"),
            "maxProductsPerSearch": max_results,
            "maxSearchPages": filters.get("max_search_pages", 1),
        }

        try:
            run = client.actor(self._actor_id).call(run_input=run_input)
            dataset_id = _dataset_id_from_run(run)
            items = list(client.dataset(dataset_id).iterate_items())
        except Exception as exc:
            raise DataSourceError(
                f"Apify Actor {self._actor_id} failed for query {query!r}"
            ) from exc

        products = [_map_apify_item(item) for item in items]
        self._cache.set(self._actor_id, query, cache_filters, products)
        return _apply_filters(products, filters)

    async def get_by_id(self, product_id: str) -> Product | None:
        """Fetch a single Amazon product by ASIN.

        This Actor does not support direct ASIN lookup, so we search by ASIN
        and return the first matching result.
        """
        products = await self.search(product_id, max_results=5)
        for product in products:
            if product.product_id.lower() == product_id.lower():
                return product
        return None


def _dataset_id_from_run(run: Any) -> str:
    """Extract default dataset ID from an Apify run (dict or Run model)."""
    if isinstance(run, dict):
        return run["defaultDatasetId"]
    return str(run.default_dataset_id)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _map_apify_item(item: dict[str, Any]) -> Product:
    """Map a raw Apify Amazon Scraper item to a normalized Product."""
    asin = item.get("asin") or item.get("productId") or item.get("url", "")
    product_id = str(asin) if asin else "unknown"

    url = item.get("url") or item.get("detailUrl") or ""
    if url and not url.startswith("http"):
        url = f"https://www.amazon.com{url}"

    title = item.get("name") or item.get("title") or "Unknown Product"
    category = item.get("categoryBreadcrumb") or item.get("category") or "unknown"

    price = _to_decimal(item.get("price")) or _to_decimal(
        item.get("buyboxWinner", {}).get("price")
    )
    original_price = _to_decimal(item.get("listPrice")) or _to_decimal(
        item.get("buyboxWinner", {}).get("listPrice")
    )

    rating = _to_float(item.get("rating")) or _to_float(item.get("stars"))
    review_count = _to_int(item.get("reviewCount")) or _to_int(
        item.get("reviewsCount")
    ) or _to_int(item.get("reviews"))
    bsr = _to_int(item.get("bestSellerRank")) or _to_int(item.get("bsr"))
    sales_volume = _to_int(item.get("salesVolume"))

    image_url = item.get("thumbnail") or item.get("image") or item.get("mainImage")
    seller = (
        item.get("seller")
        or item.get("brand")
        or item.get("buyboxWinner", {}).get("seller")
    )
    availability = item.get("availability") or item.get("inStock")
    shipping_cost = _to_decimal(item.get("shipping"))

    attributes = dict(item.get("attributes", {}))
    # Keep the raw item available for debugging without bloating the model.
    attributes.setdefault("_apify_raw", item)

    return Product(
        product_id=product_id,
        title=str(title),
        category=str(category),
        price=price or Decimal("0"),
        original_price=original_price,
        rating=rating,
        review_count=review_count,
        sales_volume=sales_volume,
        bsr=bsr,
        platform="amazon",
        url=str(url),
        image_url=str(image_url) if image_url else None,
        shipping_cost=shipping_cost,
        seller=str(seller) if seller else None,
        availability=str(availability) if availability else None,
        attributes=attributes,
    )


def _apply_filters(products: list[Product], filters: dict[str, Any]) -> list[Product]:
    """Apply lightweight post-filtering to Apify results."""
    results = list(products)

    if category := filters.get("category"):
        category = category.strip().lower().replace(" ", "_")
        results = [p for p in results if p.category == category]

    if price_min := filters.get("price_min"):
        min_price = Decimal(str(price_min))
        results = [p for p in results if p.price >= min_price]

    if price_max := filters.get("price_max"):
        max_price = Decimal(str(price_max))
        results = [p for p in results if p.price <= max_price]

    if rating_min := filters.get("rating_min"):
        min_rating = float(rating_min)
        results = [p for p in results if p.rating is not None and p.rating >= min_rating]

    limit = filters.get("limit")
    if limit is not None:
        results = results[: int(limit)]

    return results
