"""Procurement / sourcing quote lookup for selection profit calculations."""

from __future__ import annotations

import re
import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.api.monitor import monitor
from app.evidence.models import EvidenceMethod
from app.evidence.store import record_evidence
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


_LLM_PRICE_EXTRACT_PROMPT = """\
从以下 1688/Alibaba 搜索结果中提取「{product}」的人民币批发单价。\n\n规则：\n1. 只提取搜索结果中明确出现的价格数字，禁止估算或推测\n2. 如果看到价格区间（如"35-50元"），取最低值\n3. 返回 JSON 格式：{{"price": 数字, "source_text": "原文片段"}}\n4. 如果完全没有可识别的批发价格，返回 {{"price": null, "reason": "原因"}}\n\n搜索结果：\n{evidence}\n"""


def _parse_llm_price(raw: str) -> float | None:
    """从 LLM 返回的 JSON 中安全解析价格。"""
    import json

    try:
        # 去掉可能的 markdown 包裹
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        price = data.get("price")
        if price is None:
            return None
        price = float(price)
        if 1.0 <= price <= 5000.0:
            return price
        return None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _validate_price_in_text(price: float, text: str) -> bool:
    """交叉验证：LLM 抽出的价格必须在原文中出现过。"""
    # 搜索 price 整数和小数形式
    patterns = [
        str(int(price)),
        f"{price:.1f}",
        f"{price:.2f}",
        str(round(price)),
    ]
    for pat in set(patterns):
        if pat in text:
            return True
        # 也匹配 "35 元" 这种（带空格）
        if re.search(rf"\b{re.escape(pat)}\b", text):
            return True
    return False


async def _extract_price_via_llm(
    evidence_text: str, product_query: str
) -> tuple[float | None, str]:
    """用 LLM 从搜索证据中提取批发价，交叉验证后才返回。"""
    prompt = _LLM_PRICE_EXTRACT_PROMPT.format(
        product=product_query, evidence=evidence_text[:4000]
    )
    try:
        llm = get_llm()
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        price = _parse_llm_price(str(content))
        if price is not None and _validate_price_in_text(price, evidence_text):
            return price, str(content)[:200]
        return None, f"LLM 提取失败或交叉验证不通过: {str(content)[:100]}"
    except Exception as exc:
        return None, f"LLM 调用异常: {type(exc).__name__}"


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


def _record_price_evidence(
    *,
    value: float | None,
    source: str,
    confidence: float,
    evidence: list[str],
    product_id: str | None = None,
) -> None:
    """把本次采购价写进会话证据库；无会话上下文时静默跳过。"""
    if source == "web_search":
        method = EvidenceMethod.EXTRACTED
    elif source == "retail_ratio_estimate":
        method = EvidenceMethod.ESTIMATED
    else:
        method = EvidenceMethod.MISSING
    record_evidence(
        field="procurement_cost_cny",
        value=value,
        method=method,
        source=source,
        detail=evidence[0] if evidence else "",
        confidence=confidence,
        tool="procurement_quote",
        product_id=product_id,
    )


@tool
async def procurement_quote(
    product_query: str,
    amazon_price_usd: float | None = None,
    amazon_price_cny: float | None = None,
    quantity: int = 100,
    product_id: str | None = None,
) -> ProcurementQuoteOutput:
    """查询货源采购单价（优先 1688/Alibaba 网页证据），供 profit_calculator 使用。

    product_query：用于 1688 检索的品类关键词，传中文品类名效果最好
    （如「蓝牙耳机」「紫砂保温杯」）；去掉品牌与型号（如 TOZO NC9、B0H3PSK8LR），
    不要把完整英文标题或促销词原样传入。

    product_id：可选。为具体候选查价时传入该候选的 SKU/ID，证据会绑定到它，
    决策门禁按商品取用本商品自己的采购置信度。

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

    # 直接使用模型给出的品类关键词检索；工具不做隐藏改写（关键词由调用方负责，
    # 见工具 docstring 与主提示词对 product_query 的说明）。
    search_query = (
        f"1688 {product_query} 批发价 拿货价 货源价格 "
        f"OR alibaba {product_query} wholesale price CNY"
    )
    search_result: WebSearchOutput = await web_search.ainvoke(
        {"query": search_query, "max_results": 5}
    )

    if search_result.status == "ok" and search_result.results:
        blob = search_result.as_evidence(max_chars=5000)
        evidence = [
            f"{item.title} | {item.url}" for item in search_result.results[:3]
        ]
        # 第一道：正则提取
        prices = _extract_cny_candidates(blob)
        quote = _pick_quote(prices)
        if quote is not None:
            await monitor.report_tool_end(
                "procurement_quote", int((time.time() - started_at) * 1000)
            )
            _record_price_evidence(
                value=quote,
                source="web_search",
                confidence=0.7 if len(prices) >= 2 else 0.55,
                evidence=evidence,
                product_id=product_id,
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
        # 第二道：LLM 提取 + 交叉验证
        llm_price, llm_detail = await _extract_price_via_llm(blob, product_query)
        if llm_price is not None:
            await monitor.report_tool_end(
                "procurement_quote", int((time.time() - started_at) * 1000)
            )
            _record_price_evidence(
                value=llm_price,
                source="web_search",
                confidence=0.55,
                evidence=evidence,
                product_id=product_id,
            )
            return ProcurementQuoteOutput(
                product_query=product_query,
                procurement_cost_cny=llm_price,
                currency="CNY",
                moq=quantity,
                supplier_name="web_search_llm_extract",
                source="web_search",
                confidence=0.55,
                evidence=evidence,
                notes=[
                    f"LLM 从搜索证据提取价格并经交叉验证: {llm_detail}",
                    f"建议按 MOQ≈{quantity} 向货源核实后再下单",
                ],
            )
        notes.append(f"网页搜索有结果，但未能解析出可用单价 ({llm_detail})")
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
        _record_price_evidence(
            value=estimated,
            source="retail_ratio_estimate",
            confidence=0.4,
            evidence=evidence,
            product_id=product_id,
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
    _record_price_evidence(
        value=None,
        source="unavailable",
        confidence=0.0,
        evidence=evidence,
        product_id=product_id,
    )
    return ProcurementQuoteOutput(
        product_query=product_query,
        procurement_cost_cny=None,
        source="unavailable",
        confidence=0.0,
        evidence=evidence,
        notes=notes + ["缺少售价锚点，无法估算；请补充 amazon_price 或人工采购价"],
    )
