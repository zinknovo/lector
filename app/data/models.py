"""Unified product model for lector data sources."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Product(BaseModel):
    """A normalized product record from any supported platform."""

    product_id: str = Field(..., description="Platform-scoped unique identifier.")
    title: str = Field(..., description="Product title.")
    category: str = Field(..., description="Normalized category slug, e.g. kitchen_gadgets.")
    price: Decimal = Field(..., description="Current selling price.")
    original_price: Decimal | None = Field(None, description="List/strikethrough price.")
    rating: float | None = Field(None, ge=0, le=5, description="Average rating, 0-5.")
    review_count: int | None = Field(None, ge=0, description="Number of reviews.")
    sales_volume: int | None = Field(None, ge=0, description="Estimated monthly sales.")
    bsr: int | None = Field(None, ge=1, description="Best Sellers Rank.")
    platform: str = Field(..., description="Source platform, e.g. amazon, mock.")
    url: str = Field(..., description="Canonical product detail URL.")
    image_url: str | None = Field(None, description="Primary product image URL.")
    shipping_cost: Decimal | None = Field(None, description="Estimated shipping cost.")
    seller: str | None = Field(None, description="Seller or brand name.")
    availability: str | None = Field(None, description="Availability status.")
    attributes: dict[str, Any] = Field(default_factory=dict, description="Extra platform-specific attributes.")
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the record was fetched.",
    )

    @field_validator("category")
    @classmethod
    def _normalize_category(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "_")

    model_config = {
        "frozen": False,
    }
