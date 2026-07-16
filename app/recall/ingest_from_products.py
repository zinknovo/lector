"""从商品搜索结果自动生成并灌入品类知识卡。"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

from app.data.models import Product
from app.recall.category_kb import CategoryCard
from app.recall.category_norm import normalize_category
from app.recall.category_store import (
    CategoryKnowledgeStore,
    get_category_knowledge_store,
)

logger = logging.getLogger(__name__)

# 自动灌入卡的置信度上限（低于人工精修卡）
_AUTO_CONFIDENCE_CAP = 0.72
_USD_TO_CNY = Decimal("7.2")
_MAX_SUMMARY = 200

# 标题关键词 → 卖点桶（用于 attribute / bestseller 组件）
_FEATURE_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("主动降噪", ("anc", "noise cancelling", "noise-cancelling", "降噪")),
    ("运动防水", ("sport", "sports", "waterproof", "ipx", "sweat", "运动", "防水")),
    ("长续航", ("battery", "playtime", "hrs", "hour", "续航", "充电仓")),
    ("无线蓝牙", ("wireless", "bluetooth", "无线", "蓝牙")),
    ("快充", ("fast charg", "usb-c", "type-c", "快充")),
)


def _stable_card_id(category: str, card_type: str) -> str:
    """同一品类 + 类型固定 card_id，便于重复搜索幂等覆盖。"""
    digest = hashlib.sha1(f"{category}|{card_type}".encode()).hexdigest()[:10]
    return f"auto-{digest}-{card_type}"


def _price_cny(product: Product) -> float:
    return float(product.price * _USD_TO_CNY)


def _short_title(title: str, limit: int = 48) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) <= limit:
        return title
    return title[: limit - 1].rstrip() + "…"


def _match_buckets(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for label, keywords in _FEATURE_BUCKETS:
        if any(k in lowered for k in keywords):
            hits.append(label)
    return hits


def _truncate_summary(summary: str) -> str:
    if len(summary) <= _MAX_SUMMARY:
        return summary
    return summary[: _MAX_SUMMARY - 1].rstrip() + "…"


def build_category_cards_from_products(
    query: str,
    products: list[Product],
    *,
    now: datetime | None = None,
) -> list[CategoryCard]:
    """根据一次商品搜索结果生成最多 3 张结构化品类卡。"""
    if not products:
        return []

    category = normalize_category(query.strip() or products[0].category)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sample_n = len(products)
    confidence = round(
        min(_AUTO_CONFIDENCE_CAP, 0.55 + min(0.15, sample_n * 0.015)),
        2,
    )

    # --- bestseller ---
    ranked = sorted(
        products,
        key=lambda p: (
            p.review_count or 0,
            p.rating or 0.0,
            -(_price_cny(p)),
        ),
        reverse=True,
    )
    top = ranked[:3]
    feature_hits = Counter()
    for product in products:
        for label in _match_buckets(product.title):
            feature_hits[label] += 1
    components = [label for label, _ in feature_hits.most_common(3)]
    if len(components) < 2:
        # 关键词不足时用短标题兜底，保证 summary 含 ": " 与 "/"
        components = [_short_title(p.title, 18) for p in top[:3]]
        while len(components) < 2:
            components.append("热销款")
    bestseller_summary = _truncate_summary(
        f"{category}: " + " / ".join(components[:3])
    )
    bestseller_evidence = [
        f"{_short_title(p.title)} | {_price_cny(p):.0f} | "
        f"{p.platform} {p.product_id}"
        + (f", rating {p.rating}" if p.rating is not None else "")
        for p in top
    ]

    # --- attribute ---
    total_hits = sum(feature_hits.values()) or 1
    if feature_hits:
        # 归一成百分比，保证含 "%"
        parts: list[str] = []
        remaining = 100
        ordered = feature_hits.most_common(4)
        for idx, (label, count) in enumerate(ordered):
            if idx == len(ordered) - 1:
                pct = remaining
            else:
                pct = max(1, round(100 * count / total_hits))
                remaining -= pct
            parts.append(f"{label} {pct}%")
        attribute_summary = _truncate_summary("卖点侧重: " + " / ".join(parts))
        attribute_evidence = [
            f"从 {sample_n} 条搜索结果标题统计关键词分布",
            f"query={query}",
        ]
    else:
        attribute_summary = "卖点侧重: 综合热销 100%"
        attribute_evidence = [
            f"标题未命中预置卖点词典，使用综合热销兜底（n={sample_n}）"
        ]

    # --- price_range ---
    prices = sorted(_price_cny(p) for p in products)
    low, high = prices[0], prices[-1]
    mid = prices[len(prices) // 2]
    # 用样本分出三段，并带上 category_insight 可识别的中文档位词
    p25 = prices[max(0, len(prices) // 4)]
    p75 = prices[min(len(prices) - 1, (3 * len(prices)) // 4)]
    budget_hi = max(low + 1, p25)
    mid_lo = budget_hi
    mid_hi = max(mid_lo + 1, p75)
    premium_lo = mid_hi
    premium_hi = max(premium_lo + 1, high)
    price_summary = _truncate_summary(
        f"便宜款 {low:.0f}-{budget_hi:.0f} / "
        f"中档 {mid_lo:.0f}-{mid_hi:.0f} / "
        f"高端 {premium_lo:.0f}-{premium_hi:.0f}"
    )
    price_evidence = [
        f"样本价（估算 CNY，USD×{_USD_TO_CNY}）"
        f" min={low:.0f} median={mid:.0f} max={high:.0f}, n={sample_n}",
        f"query={query}",
    ]

    return [
        CategoryCard(
            card_id=_stable_card_id(category, "bestseller"),
            category=category,
            card_type="bestseller",
            summary=bestseller_summary,
            raw_evidence=bestseller_evidence[:3],
            last_updated=stamp,
            confidence=confidence,
        ),
        CategoryCard(
            card_id=_stable_card_id(category, "attribute"),
            category=category,
            card_type="attribute",
            summary=attribute_summary,
            raw_evidence=attribute_evidence[:3],
            last_updated=stamp,
            confidence=confidence,
        ),
        CategoryCard(
            card_id=_stable_card_id(category, "price_range"),
            category=category,
            card_type="price_range",
            summary=price_summary,
            raw_evidence=price_evidence[:3],
            last_updated=stamp,
            confidence=confidence,
        ),
    ]


async def ingest_products_as_category_cards(
    query: str,
    products: list[Product],
    *,
    store: CategoryKnowledgeStore | None = None,
) -> int:
    """生成品类卡并写入知识库；失败时记录日志并返回 0，不抛给调用方。"""
    try:
        cards = build_category_cards_from_products(query, products)
        if not cards:
            return 0
        backend = store or get_category_knowledge_store()
        return await backend.upsert_many(cards)
    except Exception:
        logger.exception(
            "auto ingest category cards failed for query=%r products=%d",
            query,
            len(products),
        )
        return 0
