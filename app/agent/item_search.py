"""Item search tool backed by normalized product data sources."""

import time
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor
from app.data import ApifyAmazonDataSource, MockProductDataSource, Product, ProductDataSource
from app.recall.ingest_from_products import ingest_products_as_category_cards


class Candidate(BaseModel):
    item_id: str
    platform: str
    title: str
    price: float
    currency: str
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None
    image_url: str | None = None
    seller: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ItemSearchOutput(BaseModel):
    platform: str
    candidates: list[Candidate]
    total_recall: int
    truncated: bool
    category_cards_upserted: int = 0


def _product_to_candidate(product: Product) -> Candidate:
    return Candidate(
        item_id=product.product_id,
        platform=product.platform,
        title=product.title,
        price=float(str(product.price)),
        currency="USD" if product.platform == "amazon" else "CNY",
        rating=product.rating,
        review_count=product.review_count,
        sales=product.sales_volume,
        image_url=product.image_url,
        seller=product.seller,
        attributes=product.attributes,
    )


def _source_for(platform: Literal["amazon", "mock"]) -> ProductDataSource:
    """amazon 固定走 Apify，避免工厂回退到 Mock 后再被 platform 过滤成空结果。"""
    if platform == "mock":
        return MockProductDataSource()
    return ApifyAmazonDataSource()


@tool
async def item_search(
    query: str,
    platform: Literal["amazon", "mock"],
    top_k: int = 20,
    price_max: float | None = None,
    rating_min: float | None = None,
) -> ItemSearchOutput:
    """从指定平台召回选品候选。美国站/Amazon 请用 platform=\"amazon\"（Apify 真实抓取）；本地演示用 mock。

    成功召回后会自动把结果灌入品类知识卡，供 category_insight 使用。
    """
    top_k = max(1, min(top_k, 50))
    await monitor.report_tool_start(
        "item_search", {"query": query, "platform": platform, "top_k": top_k}
    )
    started_at = time.time()
    filters: dict[str, Any] = {"limit": top_k, "max_results": top_k}
    if price_max is not None:
        filters["price_max"] = price_max
    if rating_min is not None:
        filters["rating_min"] = rating_min
    products = await _source_for(platform).search(query, **filters)
    matched = [product for product in products if product.platform == platform]
    upserted = await ingest_products_as_category_cards(query, matched)
    candidates = [_product_to_candidate(product) for product in matched]
    total_recall = len(candidates)
    await monitor.report_tool_end(
        "item_search", int((time.time() - started_at) * 1000)
    )
    return ItemSearchOutput(
        platform=platform,
        candidates=candidates[:top_k],
        total_recall=total_recall,
        truncated=total_recall > top_k,
        category_cards_upserted=upserted,
    )
