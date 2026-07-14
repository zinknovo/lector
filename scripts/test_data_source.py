"""CLI script to exercise the lector data source layer."""

import argparse
import asyncio
import json
import os
import sys

# Make sure the project root is on PYTHONPATH when running as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data import ApifyAmazonDataSource, MockProductDataSource, get_data_source
from app.data.models import Product


def _serialize(products: list[Product]) -> str:
    """Serialize products to pretty JSON."""
    return json.dumps(
        [p.model_dump(mode="json") for p in products],
        ensure_ascii=False,
        indent=2,
        default=str,
    )


async def _run_mock(query: str, **filters) -> None:
    source = MockProductDataSource()
    results = await source.search(query, **filters)
    print(f"Mock search: query={query!r}, filters={filters}, found={len(results)}")
    print(_serialize(results))


async def _run_apify(query: str, **filters) -> None:
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print(
            "ERROR: APIFY_API_TOKEN is not set. "
            "Set it in your environment or .env file to run the Apify source.",
            file=sys.stderr,
        )
        sys.exit(1)

    source = ApifyAmazonDataSource(api_token=token)
    results = await source.search(query, **filters)
    print(f"Apify search: query={query!r}, filters={filters}, found={len(results)}")
    print(_serialize(results))


async def _run_factory() -> None:
    source = get_data_source()
    print(f"Factory selected source: {type(source).__name__}")
    results = await source.search("camping")
    print(f"Found {len(results)} products via factory source")
    print(_serialize(results))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test lector product data sources.")
    parser.add_argument(
        "--source",
        choices=["mock", "apify", "factory"],
        default="factory",
        help="Which source to exercise.",
    )
    parser.add_argument("--query", default="", help="Search query.")
    parser.add_argument("--category", help="Filter by category.")
    parser.add_argument("--price-min", type=float, help="Minimum price.")
    parser.add_argument("--price-max", type=float, help="Maximum price.")
    parser.add_argument("--rating-min", type=float, help="Minimum rating.")
    parser.add_argument("--limit", type=int, help="Maximum number of results.")
    args = parser.parse_args()

    filters = {
        k: v
        for k, v in {
            "category": args.category,
            "price_min": args.price_min,
            "price_max": args.price_max,
            "rating_min": args.rating_min,
            "limit": args.limit,
        }.items()
        if v is not None
    }

    if args.source == "mock":
        await _run_mock(args.query, **filters)
    elif args.source == "apify":
        await _run_apify(args.query, **filters)
    else:
        await _run_factory()


if __name__ == "__main__":
    asyncio.run(main())
