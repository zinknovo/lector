"""Unified product model for lector data sources."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator


class Product(BaseModel):
    """A normalized product record from any supported platform."""

    product_id: str = Field(..., description="Platform-scoped unique identifier.")
    title: str = Field(..., description="Product title.")
    category: str = Field(..., description="Normalized category slug, e.g. kitchen_gadgets.")
    price: Decimal = Field(..., description="Current selling price.")
    original_price: Annotated[
        Decimal | None, Field(description="List/strikethrough price.")
    ] = None
    rating: Annotated[
        float | None, Field(ge=0, le=5, description="Average rating, 0-5.")
    ] = None
    review_count: Annotated[
        int | None, Field(ge=0, description="Number of reviews.")
    ] = None
    sales_volume: Annotated[
        int | None, Field(ge=0, description="Estimated monthly sales.")
    ] = None
    bsr: Annotated[
        int | None, Field(ge=1, description="Best Sellers Rank.")
    ] = None
    platform: str = Field(..., description="Source platform, e.g. amazon, mock.")
    url: str = Field(..., description="Canonical product detail URL.")
    image_url: Annotated[
        str | None, Field(description="Primary product image URL.")
    ] = None
    shipping_cost: Annotated[
        Decimal | None, Field(description="Estimated shipping cost.")
    ] = None
    seller: Annotated[
        str | None, Field(description="Seller or brand name.")
    ] = None
    availability: Annotated[
        str | None, Field(description="Availability status.")
    ] = None
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
