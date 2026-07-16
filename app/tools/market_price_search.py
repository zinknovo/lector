"""Multi-source selling price evidence search for revenue (market price)."""

from __future__ import annotations

import re
import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor
from app.tools.web_search import WebSearchOutput, web_search


class PriceEvidence(BaseModel):
    """A single price observation extracted from web evidence."""

    item_id: str | None = Field(
        default=None, description="Optional stable identifier for the SKU."
    )
    platform: str = Field(
        default="web", description="Where this observation comes from (web/site/platform)."
    )
    source_name: str | None = Field(default=None, description="Short source name.")
    source_url: str

    price_local: float = Field(..., gt=0, description="Observed numeric price.")
    currency_local: str = Field(
        default="USD", description="Currency code detected from the evidence."
    )

    shipping_included: bool | None = Field(
        default=None, description="Whether the evidence states shipping included."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Evidence confidence.")
    notes: list[str] = Field(default_factory=list)


class MarketPriceSearchOutput(BaseModel):
    query: str
    destination: str
    platform_hints: list[str] = Field(default_factory=list)
    evidence: list[PriceEvidence] = Field(default_factory=list)

    @property
    def best_price(self) -> float | None:
        if not self.evidence:
            return None
        ordered = sorted(self.evidence, key=lambda e: (e.confidence, e.price_local))
        return ordered[-1].price_local


_PRICE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # USD: $12.34
    (re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)"), "USD"),
    # USD: USD 12.34 / U.S. dollar 12.34 (best-effort)
    (
        re.compile(
            r"\b(?:USD|US\$|US dollars|U\.S\. ?dollars)\b\s*(\d+(?:\.\d{1,2})?)",
            re.I,
        ),
        "USD",
    ),
    # GBP: £12.34
    (re.compile(r"£\s*(\d+(?:\.\d{1,2})?)"), "GBP"),
    # EUR: €12.34
    (re.compile(r"€\s*(\d+(?:\.\d{1,2})?)"), "EUR"),
    # JPY: ¥1234 (no decimals usually)
    (re.compile(r"(?:JPY|¥)\s*(\d+(?:\.\d{1,2})?)"), "JPY"),
    # CNY: ¥123 / ￥123
    (re.compile(r"(?:CNY|RMB|¥|￥)\s*(\d+(?:\.\d{1,2})?)"), "CNY"),
)


def _extract_prices(text: str) -> list[tuple[float, str, str]]:
    """Return list of (price, currency, matched_snippet)."""
    found: list[tuple[float, str, str]] = []
    if not text:
        return found
    lower = text.lower()
    shipping_related = "shipping" in lower or "delivery" in lower
    for pattern, currency in _PRICE_PATTERNS:
        for m in pattern.finditer(text):
            try:
                value = float(m.group(1))
            except (TypeError, ValueError):
                continue
            snippet = (m.group(0) or "").strip()
            if not (0.5 <= value <= 50000):
                continue
            # Penalize shipping/delivery-related numbers because they are often fees, not item price.
            conf = 0.9 if not shipping_related else 0.65
            found.append((round(value, 2), currency, snippet))
            # conf is not stored here; downstream tool sets confidence
    return found


def _guess_confidence(extracted: list[tuple[float, str, str]], source_count: int) -> float:
    if not extracted:
        return 0.0
    # More extracted observations => higher confidence, but cap to keep conservative.
    return min(0.85, 0.45 + 0.1 * min(len(extracted), 4) + 0.05 * min(source_count, 3))


@tool
async def market_price_search(
    query: str,
    destination: str = "US",
    platform_hints: list[str] | None = None,
    item_id: str | None = None,
    platform: str = "web",
    top_results: int = 5,
) -> MarketPriceSearchOutput:
    """Search selling price evidence from the web (multi-source revenue reference).

    Notes:
    - This is a best-effort evidence extraction tool; prices may be noisy.
    - Agent must use missing_data/recommendation gating to avoid over-trusting low-confidence evidence.
    """

    destination = (destination or "US").upper()
    platform_hints = platform_hints or []
    top_results = max(1, min(int(top_results), 10))

    await monitor.report_tool_start(
        "market_price_search",
        {
            "query": query[:80],
            "destination": destination,
            "platform_hints": platform_hints[:6],
        },
    )
    started_at = time.time()

    # Build a small search plan: one broad query + optional per-platform hints.
    # Keep the number of tool calls low because web_search is expensive.
    queries: list[str] = []
    broad = f"{query} price USD"
    queries.append(broad)
    for hint in platform_hints[:3]:
        hint_q = f"{query} {hint} price"
        queries.append(hint_q)

    # Deduplicate URLs across queries
    seen_urls: set[str] = set()
    evidence: list[PriceEvidence] = []

    for q in queries[:4]:
        ws: WebSearchOutput = await web_search.ainvoke({"query": q, "max_results": top_results})
        if ws.status != "ok" or not ws.results:
            continue

        extracted_any = 0
        for idx, r in enumerate(ws.results[:top_results]):
            url = r.url.strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            prices = _extract_prices(r.content)
            if not prices:
                continue
            extracted_any += len(prices)
            # Create up to 2 evidence records per URL to avoid exploding.
            for price_local, currency_local, _snippet in prices[:2]:
                confidence = _guess_confidence([(
                    price_local,
                    currency_local,
                    _snippet,
                )], source_count=len(seen_urls))
                notes = [
                    f"Parsed from web_search result #{idx+1}",
                    f"Snippet={_snippet}" if _snippet else "No snippet",
                ]
                evidence.append(
                    PriceEvidence(
                        item_id=item_id,
                        platform=platform,
                        source_name=ws.provider,
                        source_url=url,
                        price_local=price_local,
                        currency_local=currency_local,
                        shipping_included=None,
                        confidence=round(confidence, 3),
                        notes=notes,
                    )
                )

        # If we already have enough evidence, stop early.
        if len(evidence) >= 10:
            break

        # In case we barely extracted from this query, still continue to next query.

    # Add a final conservative confidence adjustment: more unique URLs => higher best confidence.
    if evidence:
        # Re-score based on how many distinct URLs we extracted from.
        unique_urls = len({e.source_url for e in evidence})
        conf_boost = min(0.15, 0.03 * unique_urls)
        for e in evidence:
            e.confidence = min(0.95, round(e.confidence + conf_boost, 3))

    await monitor.report_tool_end(
        "market_price_search", int((time.time() - started_at) * 1000)
    )
    return MarketPriceSearchOutput(
        query=query,
        destination=destination,
        platform_hints=platform_hints,
        evidence=evidence[:20],
    )

