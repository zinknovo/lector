"""Procurement / sourcing quote lookup for selection profit calculations."""

from __future__ import annotations

import re
import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor
from app.tools.web_search import WebSearchOutput, web_search

# 当搜不到货源价时，用售价估算采购成本的默认系数（透明标注为 estimate）
_DEFAULT_COST_RATIO = 0.28
_USD_TO_CNY_FALLBACK = 7.2


class ProcurementQuoteOutput(BaseModel):
    product_query: str
    procurement_cost_cny: float | None = Field(
        default=None, description="单件采购成本（人民币）"
    )
    currency: str = "CNY"
    moq: int | None = None
    supplier_name: str | None = None
    source: Literal["web_search", "retail_ratio_estimate", "unavailable"]
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


_PRICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:¥|￥|RMB|CNY)\s*(\d+(?:\.\d{1,2})?)", re.I),
    re.compile(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块钱)"),
    re.compile(r"(?:单价|批发价|拿货价|采购价)[^\d]{0,6}(\d+(?:\.\d{1,2})?)", re.I),
    re.compile(r"\$?\s*(\d+(?:\.\d{1,2})?)\s*(?:USD|美元)", re.I),
)


def _extract_cny_candidates(text: str) -> list[float]:
    """从证据文本中提取可能的人民币单价。"""
    prices: list[float] = []
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(text):
            value = float(match.group(1))
            raw = match.group(0).lower()
            if "usd" in raw or "美元" in raw or raw.strip().startswith("$"):
                value *= _USD_TO_CNY_FALLBACK
            # 过滤明显离谱的批发单价
            if 1.0 <= value <= 5000.0:
                prices.append(round(value, 2))
    return prices


def _pick_quote(prices: list[float]) -> float | None:
    if not prices:
        return None
    ordered = sorted(prices)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    return round((ordered[n // 2 - 1] + ordered[n // 2]) / 2, 2)


def estimate_from_retail(
    *,
    amazon_price_usd: float | None,
    amazon_price_cny: float | None,
    cost_ratio: float = _DEFAULT_COST_RATIO,
) -> float | None:
    """无货源报价时，按零售价比例估算采购成本。"""
    if amazon_price_cny is not None and amazon_price_cny > 0:
        return round(amazon_price_cny * cost_ratio, 2)
    if amazon_price_usd is not None and amazon_price_usd > 0:
        return round(amazon_price_usd * _USD_TO_CNY_FALLBACK * cost_ratio, 2)
    return None


@tool
async def procurement_quote(
    product_query: str,
    amazon_price_usd: float | None = None,
    amazon_price_cny: float | None = None,
    quantity: int = 100,
) -> ProcurementQuoteOutput:
    """查询货源采购单价（优先 1688/Alibaba 网页证据），供 profit_calculator 使用。

    美国站选品 full_chain 在调用 profit_calculator 之前必须先拿采购成本。
    若网页搜不到可靠报价，会返回基于 Amazon 售价的透明估算（source=retail_ratio_estimate）。
    """
    product_query = product_query.strip()
    quantity = max(1, quantity)
    await monitor.report_tool_start(
        "procurement_quote",
        {
            "product_query": product_query,
            "quantity": quantity,
            "amazon_price_usd": amazon_price_usd,
        },
    )
    started_at = time.time()
    notes: list[str] = []
    evidence: list[str] = []

    search_query = (
        f"1688 {product_query} 批发价 拿货价 OR alibaba {product_query} wholesale price CNY"
    )
    search_result: WebSearchOutput = await web_search.ainvoke(
        {"query": search_query, "max_results": 5}
    )

    if search_result.status == "ok" and search_result.results:
        blob = search_result.as_evidence(max_chars=5000)
        evidence = [
            f"{item.title} | {item.url}" for item in search_result.results[:3]
        ]
        prices = _extract_cny_candidates(blob)
        quote = _pick_quote(prices)
        if quote is not None:
            await monitor.report_tool_end(
                "procurement_quote", int((time.time() - started_at) * 1000)
            )
            return ProcurementQuoteOutput(
                product_query=product_query,
                procurement_cost_cny=quote,
                currency="CNY",
                moq=quantity,
                supplier_name="web_search_aggregate",
                source="web_search",
                confidence=0.7 if len(prices) >= 2 else 0.55,
                evidence=evidence,
                notes=[
                    f"从网页证据解析到 {len(prices)} 个候选价，取中位数",
                    f"建议按 MOQ≈{quantity} 向货源核实后再下单",
                ],
            )
        notes.append("网页搜索有结果，但未能解析出可用单价")
    else:
        notes.append(
            search_result.error or "网页搜索不可用，无法获取货源报价证据"
        )

    estimated = estimate_from_retail(
        amazon_price_usd=amazon_price_usd,
        amazon_price_cny=amazon_price_cny,
    )
    if estimated is not None:
        await monitor.report_tool_end(
            "procurement_quote", int((time.time() - started_at) * 1000)
        )
        return ProcurementQuoteOutput(
            product_query=product_query,
            procurement_cost_cny=estimated,
            currency="CNY",
            moq=quantity,
            supplier_name=None,
            source="retail_ratio_estimate",
            confidence=0.4,
            evidence=evidence,
            notes=notes
            + [
                f"使用零售价 × {_DEFAULT_COST_RATIO:.0%} 估算采购成本",
                "仅供利润试算；正式 recommend 前请换成真实 1688/工厂报价",
            ],
        )

    await monitor.report_tool_end(
        "procurement_quote", int((time.time() - started_at) * 1000)
    )
    return ProcurementQuoteOutput(
        product_query=product_query,
        procurement_cost_cny=None,
        source="unavailable",
        confidence=0.0,
        evidence=evidence,
        notes=notes + ["缺少售价锚点，无法估算；请补充 amazon_price 或人工采购价"],
    )
