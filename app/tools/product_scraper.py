"""Platform-aware product scraping tool for the agent."""

import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor
from app.data import ApifyAmazonDataSource, MockProductDataSource, Product
from app.data.base import ProductDataSource
from app.recall.ingest_from_products import ingest_products_as_category_cards


class ProductScraperOutput(BaseModel):
    products: list[Product]
    platform: str
    source: str
    query: str
    category_cards_upserted: int = 0


def _get_source(platform: Literal["amazon", "mock"]) -> ProductDataSource:
    if platform == "amazon":
        return ApifyAmazonDataSource()
    return MockProductDataSource()


@tool
async def product_scraper(
    platform: Literal["amazon", "mock"],
    query: str,
    max_results: int = 10,
) -> ProductScraperOutput:
    """抓取指定平台商品。美国站 Amazon 真实选品请用 platform=\"amazon\"。

    与 item_search 共用数据源；成功后同样会自动灌入品类知识卡。
    需要原始 Product 列表时优先用本工具；只要候选列表时可用 item_search。
    """
    max_results = max(1, min(max_results, 50))
    await monitor.report_tool_start(
        "product_scraper",
        {"platform": platform, "query": query, "max_results": max_results},
    )
    started_at = time.time()
    source = _get_source(platform)
    products = await source.search(query, limit=max_results, max_results=max_results)
    clipped = products[:max_results]
    upserted = await ingest_products_as_category_cards(query, clipped)
    await monitor.report_tool_end(
        "product_scraper", int((time.time() - started_at) * 1000)
    )
    return ProductScraperOutput(
        products=clipped,
        platform=platform,
        source=type(source).__name__,
        query=query,
        category_cards_upserted=upserted,
    )
