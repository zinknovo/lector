"""Platform-aware product scraping tool for the agent."""

import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor
from app.data import ApifyAmazonDataSource, MockProductDataSource, Product
from app.data.base import ProductDataSource


class ProductScraperOutput(BaseModel):
    products: list[Product]
    platform: str
    source: str
    query: str


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
    """Scrape normalized products from a supported platform."""
    max_results = max(1, min(max_results, 50))
    await monitor.report_tool_start(
        "product_scraper",
        {"platform": platform, "query": query, "max_results": max_results},
    )
    started_at = time.time()
    source = _get_source(platform)
    products = await source.search(query, limit=max_results, max_results=max_results)
    await monitor.report_tool_end(
        "product_scraper", int((time.time() - started_at) * 1000)
    )
    return ProductScraperOutput(
        products=products[:max_results],
        platform=platform,
        source=type(source).__name__,
        query=query,
    )
