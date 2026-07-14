"""Live exchange-rate lookup with in-process caching."""

import json
import re
import time
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.api.monitor import monitor
from app.tools.web_search import WebSearchOutput, web_search


class ExchangeRateOutput(BaseModel):
    source_currency: str
    target_currency: str
    rate: float = Field(gt=0)
    source: str


_CACHE: dict[tuple[str, str], tuple[datetime, float]] = {}
_CACHE_TTL = timedelta(hours=1)


def _parse_rate(content: str) -> float:
    try:
        parsed = json.loads(content)
        value = parsed["rate"] if isinstance(parsed, dict) else parsed
        rate = float(value)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", content)
        if not match:
            raise ValueError("No exchange rate found")
        rate = float(match.group(1))
    if rate <= 0:
        raise ValueError("Exchange rate must be positive")
    return rate


@tool
async def exchange_rate(
    source_currency: str, target_currency: str = "CNY"
) -> ExchangeRateOutput:
    """Look up how many target-currency units equal one source-currency unit."""
    source_currency = source_currency.upper()
    target_currency = target_currency.upper()
    await monitor.report_tool_start(
        "exchange_rate", {"source": source_currency, "target": target_currency}
    )
    started_at = time.time()
    if source_currency == target_currency:
        result = ExchangeRateOutput(
            source_currency=source_currency,
            target_currency=target_currency,
            rate=1.0,
            source="identity",
        )
    else:
        key = (source_currency, target_currency)
        cached = _CACHE.get(key)
        now = datetime.now(timezone.utc)
        if cached and now - cached[0] < _CACHE_TTL:
            result = ExchangeRateOutput(
                source_currency=source_currency,
                target_currency=target_currency,
                rate=cached[1],
                source="memory_cache",
            )
        else:
            search_result: WebSearchOutput = await web_search.ainvoke(
                {"query": f"1 {source_currency} to {target_currency} exchange rate today"}
            )
            evidence = (
                search_result.as_evidence(max_chars=4000)
                if search_result.status == "ok"
                else ""
            )
            if not evidence:
                raise RuntimeError(
                    f"无法获取 {source_currency}/{target_currency} 实时汇率"
                )
            try:
                response = await get_llm().ainvoke(
                    [
                        ("system", 'Extract the current exchange rate. Return only JSON: {"rate": number}.'),
                        ("user", evidence),
                    ]
                )
                content = response.content if isinstance(response.content, str) else str(response.content)
                rate = _parse_rate(content)
            except (RuntimeError, ValueError, TypeError):
                raise RuntimeError(
                    f"无法获取 {source_currency}/{target_currency} 实时汇率"
                ) from None
            _CACHE[key] = (now, rate)
            result = ExchangeRateOutput(
                source_currency=source_currency,
                target_currency=target_currency,
                rate=rate,
                source="web_search+llm",
            )
    await monitor.report_tool_end("exchange_rate", int((time.time() - started_at) * 1000))
    return result
