"""Abstract base class for lector product data sources."""

from abc import ABC, abstractmethod

from app.data.models import Product


class ProductDataSource(ABC):
    """Abstract interface for product search and lookup."""

    @abstractmethod
    async def search(self, query: str, **filters) -> list[Product]:
        """Search for products matching the query and optional filters.

        Common filters:
            category (str): Exact category slug match.
            price_min (Decimal | float): Minimum price (inclusive).
            price_max (Decimal | float): Maximum price (inclusive).
            rating_min (float): Minimum rating (inclusive).
        """

    @abstractmethod
    async def get_by_id(self, product_id: str) -> Product | None:
        """Return a single product by its platform-scoped ID, or None."""
