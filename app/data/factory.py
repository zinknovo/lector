"""Factory for creating the configured product data source."""

import os
import warnings

from app.data.apify_source import ApifyAmazonDataSource, DataSourceError
from app.data.base import ProductDataSource
from app.data.mock_source import MockProductDataSource


def get_data_source() -> ProductDataSource:
    """Return a ProductDataSource based on environment configuration.

    Preference order:
      1. USE_MOCK=true -> MockProductDataSource.
      2. USE_MOCK=false and APIFY_API_TOKEN is set -> ApifyAmazonDataSource.
      3. USE_MOCK=false but APIFY_API_TOKEN is missing -> MockProductDataSource (warn).
      4. USE_MOCK unset and APIFY_API_TOKEN is set -> ApifyAmazonDataSource.
      5. USE_MOCK unset and APIFY_API_TOKEN is missing -> MockProductDataSource.
    """
    use_mock_raw = os.environ.get("USE_MOCK")
    apify_token = os.environ.get("APIFY_API_TOKEN")

    if use_mock_raw is not None:
        use_mock = use_mock_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        use_mock = not bool(apify_token)

    if use_mock:
        if use_mock_raw is not None and use_mock_raw.strip().lower() == "false" and not apify_token:
            warnings.warn(
                "USE_MOCK=false but APIFY_API_TOKEN is not set; falling back to MockProductDataSource.",
                stacklevel=2,
            )
        return MockProductDataSource()

    try:
        return ApifyAmazonDataSource(api_token=apify_token)
    except DataSourceError as exc:
        warnings.warn(
            f"Failed to initialize ApifyAmazonDataSource: {exc}; falling back to MockProductDataSource.",
            stacklevel=2,
        )
        return MockProductDataSource()
