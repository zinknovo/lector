"""品类洞察工具：查询品类的结构化常识。"""

import os
import re
import time
from typing import Any, Literal

from langchain_core.tools import tool
from opensearchpy import OpenSearch
from pydantic import BaseModel

from app.api.monitor import monitor
from app.recall.category_kb import CategoryCard
from app.recall.category_norm import normalize_category
from app.recall.towers import tower_client


class Bestseller(BaseModel):
    """品类爆款信息。"""

    name: str
    typical_price_cny: float
    why_popular: str


class AttributeDist(BaseModel):
    """属性分布。"""

    name: str
    distribution: dict[str, float]  # {"尼龙": 0.6, "帆布": 0.25, ...}


class PriceTier(BaseModel):
    """价格档位。"""

    tier: Literal["budget", "mid", "premium"]
    range_cny: tuple[float, float]
    notes: str


class CategoryInsightOutput(BaseModel):
    """品类洞察输出。"""

    category: str
    components: list[str]  # 这个品类典型由哪几件组成（适用于"套"）
    bestsellers: list[Bestseller]
    attributes: list[AttributeDist]
    price_tiers: list[PriceTier]
    confidence: float  # 整体置信度


INDEX_NAME = os.environ.get("CATEGORY_KB_INDEX", "lector_category_kb")
SEARCH_PIPELINE_NAME = os.environ.get(
    "CATEGORY_KB_SEARCH_PIPELINE", "lector_hybrid_pipeline"
)

_kb_client = OpenSearch(
    hosts=[{"host": os.environ["OPENSEARCH_HOST"], "port": 9200}],
    http_auth=(os.environ["OPENSEARCH_USER"], os.environ["OPENSEARCH_PASS"]),
    use_ssl=False,
)


async def _recall_cards(category: str, top_k: int) -> list[CategoryCard]:
    """Hybrid 检索：KNN 向量召回 + BM25 全文匹配，引擎层加权融合。"""
    emb = await tower_client.encode_query(category)

    body: dict[str, Any] = {
        "size": top_k,
        "query": {
            "hybrid": {
                "queries": [
                    # 子路 1: KNN 向量语义召回
                    {"knn": {"content_vector": {"vector": emb, "k": top_k}}},
                    # 子路 2: BM25 中文全文匹配（category 字段权重 x2）
                    {
                        "multi_match": {
                            "query": category,
                            "fields": ["category^2", "summary"],
                            "analyzer": "ik_max_word",
                        }
                    },
                ]
            }
        },
        # 不要把高维向量原样返回，减少带宽
        "_source": {"excludes": ["content_vector"]},
    }

    # search_pipeline 在 OpenSearch 端配：
    # normalization=min_max, combination=arithmetic_mean, weights=[0.7, 0.3]
    # 完整 DSL 参见讲义第 4-1 章 §6「OpenSearch Hybrid Query 最小配方」
    resp = _kb_client.search(
        index=INDEX_NAME,
        body=body,
        params={"search_pipeline": SEARCH_PIPELINE_NAME},
    )

    cards: list[CategoryCard] = []
    for hit in resp["hits"]["hits"]:
        cards.append(CategoryCard(**hit["_source"]))
    return cards


def _split_by_type(cards: list[CategoryCard]) -> dict[str, list[CategoryCard]]:
    bag: dict[str, list[CategoryCard]] = {
        "bestseller": [],
        "attribute": [],
        "price_range": [],
    }
    for c in cards:
        bag.setdefault(c.card_type, []).append(c)
    return bag


def _extract_components(bestseller_cards: list[CategoryCard]) -> list[str]:
    """从爆款卡片 summary 中提取典型组件（"套装类"才有意义）。"""
    found: set[str] = set()
    for c in bestseller_cards:
        # CategoryCard.summary 写法约定: "旅行三件套: 洗漱包 / 鞋包 / 数码线..."
        if ": " in c.summary and "/" in c.summary:
            parts = c.summary.split(": ", 1)[1]
            for token in parts.split("/"):
                token = token.strip()
                if token:
                    found.add(token)
    return sorted(found)


def _extract_bestsellers(cards: list[CategoryCard]) -> list[Bestseller]:
    out: list[Bestseller] = []
    for c in cards:
        # CategoryCard 在灌库时已结构化（实际见 raw_evidence 里的爬虫字段）
        evidences = c.raw_evidence
        if not evidences:
            continue
        # 极简: 第一条证据按 "name | price | reason" 拆
        for line in evidences:
            try:
                name, price, reason = [s.strip() for s in line.split("|")]
                out.append(
                    Bestseller(
                        name=name,
                        typical_price_cny=float(price),
                        why_popular=reason,
                    )
                )
            except ValueError:
                continue
    return out[:5]


def _extract_attributes(cards: list[CategoryCard]) -> list[AttributeDist]:
    out: list[AttributeDist] = []
    for c in cards:
        # CategoryCard.summary: "材质: 尼龙 60% / 帆布 25% / 牛津布 15%"
        if ": " not in c.summary:
            continue
        attr_name, dist_str = c.summary.split(": ", 1)
        dist: dict[str, float] = {}
        for token in dist_str.split("/"):
            token = token.strip()
            if not token:
                continue
            parts = token.rsplit(" ", 1)
            if len(parts) == 2 and parts[1].endswith("%"):
                try:
                    dist[parts[0]] = float(parts[1].rstrip("%")) / 100
                except ValueError:
                    pass
        if dist:
            out.append(AttributeDist(name=attr_name.strip(), distribution=dist))
    return out


def _extract_price_tiers(cards: list[CategoryCard]) -> list[PriceTier]:
    tiers: list[PriceTier] = []
    label_map: dict[Literal["budget", "mid", "premium"], str] = {
        "budget": "便宜款",
        "mid": "中档",
        "premium": "高端",
    }
    for tier_key, label in label_map.items():
        for c in cards:
            if label in c.summary:
                # 简化：靠正则提一对数字区间
                m = re.search(r"(\d+)\s*[—-]\s*(\d+)", c.summary)
                if m:
                    tiers.append(
                        PriceTier(
                            tier=tier_key,
                            range_cny=(float(m.group(1)), float(m.group(2))),
                            notes=c.summary,
                        )
                    )
                    break
    return tiers


@tool
async def category_insight(
    category: str,
    depth: Literal["quick", "deep"] = "quick",
) -> CategoryInsightOutput:
    """获取一个品类的结构化常识：典型组件 / 爆款 / 属性分布 / 价格档位。

    Args:
        category: 标准化品类名，例如 "旅行三件套" / "咖啡杯" / "威士忌酒杯"。
        depth: quick 只查爆款 + 价格档；deep 同时查属性图谱（更慢）。

    Returns:
        CategoryInsightOutput: 已经被压缩过的结构化常识，不含 RAG 原文。
    """
    await monitor.report_tool_start("category_insight", {"category": category, "depth": depth})
    t0 = time.time()

    category = normalize_category(category)

    top_k = 8 if depth == "quick" else 15
    cards = await _recall_cards(category, top_k)
    grouped = _split_by_type(cards)

    components = _extract_components(grouped["bestseller"])
    bestsellers = _extract_bestsellers(grouped["bestseller"])
    price_tiers = _extract_price_tiers(grouped["price_range"])

    if depth == "deep":
        attributes = _extract_attributes(grouped["attribute"])
    else:
        attributes = []

    confidence = (
        sum(c.confidence for c in cards) / len(cards) if cards else 0.0
    )

    await monitor.report_tool_end(
        "category_insight", int((time.time() - t0) * 1000)
    )
    return CategoryInsightOutput(
        category=category,
        components=components,
        bestsellers=bestsellers,
        attributes=attributes,
        price_tiers=price_tiers,
        confidence=round(confidence, 2),
    )
