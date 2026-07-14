import asyncio

from app.tools.product_scraper import ProductScraperOutput, product_scraper


def test_product_scraper_returns_mock_products() -> None:
    async def run() -> ProductScraperOutput:
        return await product_scraper.ainvoke(
            {"platform": "mock", "query": "camping", "max_results": 3}
        )

    result = asyncio.run(run())
    assert result.platform == "mock"
    assert len(result.products) == 3
    assert all(product.platform == "mock" for product in result.products)
