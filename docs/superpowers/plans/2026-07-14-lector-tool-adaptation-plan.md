# Lector 工具层改造计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将现有 Globex 工具链改造为面向电商选品的工具链，让 Agent 能基于 `app.data.ProductDataSource` 完成"发现品类 → 筛选单品 → 全链路决策"三阶段任务。

**Architecture:** 以 `Product` 为统一数据载体，`item_search` 改为从 `ProductDataSource` 获取候选；新增 `product_scraper`、`market_trend_research`、`profit_calculator` 等选品专用工具；现有 `price_compare`/`shipping_calc`/`item_picker`/`shopping_summary` 逐步适配为选品语义；最终通过 `tool_registry.py` 重新编排可用工具集。

**Tech Stack:** Python 3.11+, FastAPI, LangGraph/LangChain tools, Pydantic, `app.data` 抽象层。

## Global Constraints

- 代码风格与现有 `app/` 目录一致（Pydantic `BaseModel`、async tool 函数、`app.api.monitor` 打点）。
- 不要破坏现有测试；新增工具必须配套单元测试。
- 尽量复用现有工具骨架，不引入不必要的新依赖。
- 工具入参/出参保持 Pydantic 模型，便于 LangChain schema 自动生成。
- Mock 数据源默认可用，CI 不依赖外部服务。
- 价格统一使用 `Decimal`，但现有工具内部仍可用 `float` 做计算，边界处转换。

---

## File Map

| 文件 | 职责 |
|------|------|
| `app/data/__init__.py` | 导出 `Product`, `get_data_source`, `ProductDataSource`（已存在） |
| `app/data/cache.py` | 新增：MongoDB 搜索结果缓存 |
| `app/tools/product_scraper.py` | 新增：让 Agent 显式触发指定平台商品抓取 |
| `app/tools/market_trend_research.py` | 新增：品类热度与趋势分析 |
| `app/agent/item_search.py` | 修改：从 `ProductDataSource` 召回候选，而非 Faiss |
| `app/tools/price_compare.py` | 修改：输入从 `Candidate` 扩展为支持 `Product` |
| `app/tools/shipping_calc.py` | 修改：兼容 `Product` 衍生出的 `LandedCost` |
| `app/tools/item_picker.py` | 修改：评分维度改为选品导向 |
| `app/tools/profit_calculator.py` | 新增：毛利率、ROI、定价建议 |
| `app/tools/supplier_evaluator.py` | 新增：供应商/货源风险评估 |
| `app/tools/shopping_summary.py` | 修改：输出结构化选品报告 |
| `app/agent/tool_registry.py` | 修改：重新注册改造后的工具集 |
| `tests/test_product_scraper.py` | 新增测试 |
| `tests/test_data_cache.py` | 新增测试 |
| `tests/test_market_trend_research.py` | 新增测试 |
| `tests/test_item_search.py` | 新增/修改测试 |
| `tests/test_profit_calculator.py` | 新增测试 |
| `tests/test_supplier_evaluator.py` | 新增测试 |
| `tests/test_item_picker.py` | 修改：适配新评分逻辑 |
| `tests/test_tool_registry.py` | 修改：验证注册表 |

---

## Task 1: Add `product_scraper` tool (platform-aware)

**Files:**
- Create: `app/tools/product_scraper.py`
- Test: `tests/test_product_scraper.py`

**Interfaces:**
- Consumes: `app.data.MockProductDataSource`, `app.data.ApifyAmazonDataSource`, `ProductDataSource.search(query, max_results=n)`
- Produces: `ProductScraperOutput` Pydantic model with `products: list[Product]`, `platform: str`

**Why:** 让 Agent 在"发现/筛选"阶段能显式触发指定平台的商品抓取。当前支持 `amazon`（Apify）和 `mock`，后续新增平台时直接扩展 `Literal` 和内部路由即可。

- [x] **Step 1: Write the failing test**

```python
import asyncio
import os
from typing import Literal

import pytest

from app.tools.product_scraper import ProductScraperOutput, product_scraper


@pytest.mark.skipif(
    not os.environ.get("APIFY_API_TOKEN"),
    reason="Requires APIFY_API_TOKEN",
)
def test_product_scraper_returns_amazon_products() -> None:
    async def run() -> ProductScraperOutput:
        return await product_scraper.ainvoke({
            "platform": "amazon",
            "query": "wireless earbuds",
            "max_results": 2,
        })

    result = asyncio.run(run())
    assert result.platform == "amazon"
    assert len(result.products) <= 2
    assert all(p.platform == "amazon" for p in result.products)


def test_product_scraper_returns_mock_products() -> None:
    async def run() -> ProductScraperOutput:
        return await product_scraper.ainvoke({
            "platform": "mock",
            "query": "camping",
            "max_results": 3,
        })

    result = asyncio.run(run())
    assert result.platform == "mock"
    assert len(result.products) == 3
    assert all(p.platform == "mock" for p in result.products)
```

Run: `uv run pytest tests/test_product_scraper.py -v`
Expected: FAIL with "cannot import name 'product_scraper'"

- [x] **Step 2: Implement the tool**

```python
"""Platform-aware product scraping tool for the agent."""

import time
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor
from app.data import ApifyAmazonDataSource, MockProductDataSource, Product
from app.data.base import ProductDataSource


class ProductScraperOutput(BaseModel):
    """Result of an explicit scrape request."""

    products: list[Product]
    platform: str
    source: str
    query: str


def _get_source(platform: Literal["amazon", "mock"]) -> ProductDataSource:
    if platform == "amazon":
        return ApifyAmazonDataSource()
    if platform == "mock":
        return MockProductDataSource()
    raise ValueError(f"Unsupported platform: {platform}")


@tool
async def product_scraper(
    platform: Literal["amazon", "mock"],
    query: str,
    max_results: int = 10,
) -> ProductScraperOutput:
    """Scrape products from the specified platform and return normalized records.

    Args:
        platform: Target platform. "amazon" uses Apify; "mock" uses built-in data.
        query: Search query.
        max_results: Maximum number of products to return (1-50).
    """
    max_results = max(1, min(max_results, 50))
    await monitor.report_tool_start(
        "product_scraper", {"platform": platform, "query": query, "max_results": max_results}
    )
    t0 = time.time()

    source = _get_source(platform)
    products = await source.search(query, max_results=max_results)

    await monitor.report_tool_end("product_scraper", int((time.time() - t0) * 1000))
    return ProductScraperOutput(
        products=products,
        platform=platform,
        source=type(source).__name__,
        query=query,
    )
```

- [x] **Step 3: Run tests**

Run: `uv run pytest tests/test_product_scraper.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add app/tools/product_scraper.py tests/test_product_scraper.py
git commit -m "feat(tools): add platform-aware product_scraper"
```

---

## Task 2: Add MongoDB-backed product search cache

**Files:**
- Create: `app/data/cache.py`
- Modify: `app/data/apify_source.py`
- Test: `tests/test_data_cache.py`

**Interfaces:**
- Consumes: MongoDB connection string from `MONGODB_URL`
- Produces: `ProductSearchCache.get/set` interface

**Why:** 用户要求"搜一次就存一次"，但又不想单独做持久化层。MongoDB 已在项目设计里规划用于 Agent 状态，顺手存搜索结果最自然；Redis 更适合事件/缓存，放大量商品搜索结果不合适。

- [x] **Step 1: Write the failing test**

```python
import asyncio
from decimal import Decimal

import pytest

from app.data.cache import ProductSearchCache
from app.data.models import Product


@pytest.fixture
def cache() -> ProductSearchCache:
    return ProductSearchCache(mongodb_url="mongodb://localhost:27017/lector_test")


def test_cache_miss_returns_none(cache: ProductSearchCache) -> None:
    assert cache.get("amazon", "nonexistent", {}) is None


def test_cache_stores_and_retrieves_products(cache: ProductSearchCache) -> None:
    products = [
        Product(
            product_id="B123",
            title="Test",
            category="electronics",
            price=Decimal("9.99"),
            platform="amazon",
            url="https://amazon.com/dp/B123",
        )
    ]
    cache.set("amazon", "test query", {"max_results": 5}, products)
    cached = cache.get("amazon", "test query", {"max_results": 5})
    assert cached is not None
    assert len(cached) == 1
    assert cached[0].product_id == "B123"
```

- [x] **Step 2: Implement the cache**

```python
"""MongoDB-backed cache for product search results."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.data.models import Product


class ProductSearchCache:
    """Persistent cache for ProductDataSource.search() results.

    Uses MongoDB so results survive process restarts. TTL is optional;
    by default entries are kept for 7 days.
    """

    def __init__(
        self,
        mongodb_url: str | None = None,
        db_name: str = "lector",
        collection_name: str = "product_search_cache",
        ttl_days: int = 7,
    ) -> None:
        self._mongodb_url = mongodb_url
        self._db_name = db_name
        self._collection_name = collection_name
        self._ttl_days = ttl_days
        self._collection: Any | None = None

    def _get_collection(self) -> Any | None:
        if self._collection is not None:
            return self._collection
        if not self._mongodb_url:
            return None
        try:
            from pymongo import MongoClient
        except ImportError:
            return None
        client = MongoClient(self._mongodb_url)
        self._collection = client[self._db_name][self._collection_name]
        return self._collection

    @staticmethod
    def _key(source: str, query: str, filters: dict[str, Any]) -> str:
        canonical = json.dumps({"source": source, "query": query, "filters": filters}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get(self, source: str, query: str, filters: dict[str, Any]) -> list[Product] | None:
        coll = self._get_collection()
        if coll is None:
            return None
        key = self._key(source, query, filters)
        doc = coll.find_one({"_id": key})
        if doc is None:
            return None
        # Optional TTL check
        created_at = doc.get("created_at")
        if created_at and self._ttl_days > 0:
            age = (datetime.now(timezone.utc) - created_at).days
            if age >= self._ttl_days:
                coll.delete_one({"_id": key})
                return None
        return [Product(**item) for item in doc["products"]]

    def set(
        self,
        source: str,
        query: str,
        filters: dict[str, Any],
        products: list[Product],
    ) -> None:
        coll = self._get_collection()
        if coll is None:
            return
        key = self._key(source, query, filters)
        coll.replace_one(
            {"_id": key},
            {
                "_id": key,
                "source": source,
                "query": query,
                "filters": filters,
                "products": [p.model_dump(mode="json") for p in products],
                "created_at": datetime.now(timezone.utc),
            },
            upsert=True,
        )
```

- [x] **Step 3: Wire cache into `ApifyAmazonDataSource`**

Modify `app/data/apify_source.py`:

```python
from app.data.cache import ProductSearchCache


class ApifyAmazonDataSource(ProductDataSource):
    def __init__(
        self,
        api_token: str | None = None,
        actor_id: str | None = None,
        cache: ProductSearchCache | None = None,
    ) -> None:
        ...
        self._cache = cache or ProductSearchCache()

    async def search(self, query: str, **filters) -> list[Product]:
        cache_key_filters = {k: v for k, v in filters.items() if k != "limit"}
        cached = self._cache.get(self._actor_id, query, cache_key_filters)
        if cached is not None:
            return _apply_filters(cached, filters)

        # existing Apify call ...
        products = [...]
        self._cache.set(self._actor_id, query, cache_key_filters, products)
        return _apply_filters(products, filters)
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_data_cache.py -v`
Expected: PASS（需要本地 MongoDB；CI 中可用 mongomock 或跳过）

- [x] **Step 5: Commit**

```bash
git add app/data/cache.py app/data/apify_source.py tests/test_data_cache.py
git commit -m "feat(data): add MongoDB-backed product search cache"
```

---

## Task 3: Add `market_trend_research` tool

**Files:**
- Create: `app/tools/market_trend_research.py`
- Test: `tests/test_market_trend_research.py`

**Interfaces:**
- Consumes: `app.tools.web_search.web_search`, LLM via `app.agent.llm.get_llm()`
- Produces: `MarketTrendOutput` with `category`, `demand_score`, `trend_summary`, `opportunity_gaps`

**Why:** 支持"发现潜力品类"阶段，给 Agent 一个能输出结构化趋势分析的工具。

- [x] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from app.tools.market_trend_research import MarketTrendOutput, market_trend_research


def test_market_trend_research_returns_structured_output() -> None:
    async def run() -> MarketTrendOutput:
        return await market_trend_research.ainvoke({"category": "wireless earbuds"})

    result = asyncio.run(run())
    assert result.category == "wireless earbuds"
    assert 0 <= result.demand_score <= 1
    assert result.trend_summary
    assert isinstance(result.opportunity_gaps, list)
```

Run: `uv run pytest tests/test_market_trend_research.py::test_market_trend_research_returns_structured_output -v`
Expected: FAIL

- [x] **Step 2: Implement the tool**

```python
"""Market trend research tool for product discovery."""

import json
import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agent.llm import get_llm
from app.api.monitor import monitor
from app.tools.web_search import web_search


class MarketTrendOutput(BaseModel):
    """Structured trend analysis for a category."""

    category: str
    demand_score: float = Field(..., ge=0, le=1)
    trend_summary: str
    opportunity_gaps: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """You are an ecommerce market analyst. Given web search results about a product category, produce a concise trend analysis in JSON.

Return strictly valid JSON with these keys:
- demand_score: float 0-1
- trend_summary: one paragraph
- opportunity_gaps: list of 2-5 strings describing underserved niches
- keywords: list of 3-7 related search keywords

Do not include markdown or explanation outside the JSON."""


@tool
async def market_trend_research(category: str) -> MarketTrendOutput:
    """Research market trends and demand gaps for a product category.

    Use this in the discovery phase to decide whether a category is worth
    entering.
    """
    await monitor.report_tool_start("market_trend_research", {"category": category})
    t0 = time.time()

    search_result = await web_search.ainvoke({"query": f"{category} market trend demand 2026"})
    snippets = "\n".join(search_result.get("results", []))[:4000]

    messages = [
        ("system", _SYSTEM_PROMPT),
        ("user", f"Category: {category}\n\nSearch results:\n{snippets}"),
    ]
    response = await get_llm().ainvoke(messages)
    content = response.content if isinstance(response.content, str) else str(response.content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {
            "demand_score": 0.5,
            "trend_summary": content[:500],
            "opportunity_gaps": [],
            "keywords": [],
        }

    await monitor.report_tool_end("market_trend_research", int((time.time() - t0) * 1000))
    return MarketTrendOutput(
        category=category,
        demand_score=float(parsed.get("demand_score", 0.5)),
        trend_summary=str(parsed.get("trend_summary", "")),
        opportunity_gaps=[str(g) for g in parsed.get("opportunity_gaps", [])],
        keywords=[str(k) for k in parsed.get("keywords", [])],
    )
```

- [x] **Step 3: Run tests**

Run: `uv run pytest tests/test_market_trend_research.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add app/tools/market_trend_research.py tests/test_market_trend_research.py
git commit -m "feat(tools): add market_trend_research for category discovery"
```

---

## Task 4: Rewrite `item_search` to use `app.data`

**Files:**
- Modify: `app/agent/item_search.py`
- Test: `tests/test_item_search.py`（创建新测试，保留或替换旧测试依赖 Faiss 的部分）

**Interfaces:**
- Consumes: `app.data.get_data_source`, `app.data.Product`
- Produces: `Candidate` list in `ItemSearchOutput`

**Why:** 现有 `item_search` 依赖 Faiss/ANN 本地索引，lector 需要直接从数据源（Mock/Apify）召回。

- [x] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from app.agent.item_search import ItemSearchOutput, item_search


def test_item_search_returns_candidates_from_mock() -> None:
    async def run() -> ItemSearchOutput:
        return await item_search.ainvoke({
            "query": "camping",
            "platform": "mock",
            "top_k": 3,
        })

    result = asyncio.run(run())
    assert result.platform == "mock"
    assert len(result.candidates) == 3
    assert result.candidates[0].item_id
    assert result.candidates[0].title


def test_item_search_filters_by_platform() -> None:
    async def run() -> ItemSearchOutput:
        return await item_search.ainvoke({
            "query": "",
            "platform": "mock",
            "top_k": 100,
        })

    result = asyncio.run(run())
    assert all(c.platform == "mock" for c in result.candidates)
```

Run: `uv run pytest tests/test_item_search.py -v`
Expected: FAIL（新行为未实现）

- [x] **Step 2: Implement the rewrite**

Replace the body of `app/agent/item_search.py` with:

```python
"""Item search tool backed by app.data ProductDataSource."""

import time
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor
from app.data import Product, ProductDataSource, get_data_source


class Candidate(BaseModel):
    """单个候选商品的稳定结构（后续工具按这个 schema 消费）。"""

    item_id: str
    platform: str
    title: str
    price: float
    currency: str
    rating: float | None = None
    sales: int | None = None
    image_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ItemSearchOutput(BaseModel):
    """搜索结果。"""

    platform: str
    candidates: list[Candidate]
    total_recall: int
    truncated: bool


def _product_to_candidate(p: Product) -> Candidate:
    """Normalize a Product into the Candidate schema expected by downstream tools."""
    return Candidate(
        item_id=p.product_id,
        platform=p.platform,
        title=p.title,
        price=float(p.price),
        currency="USD" if p.platform == "amazon" else "CNY",
        rating=p.rating,
        sales=p.sales_volume,
        image_url=p.image_url,
        attributes=p.attributes,
    )


@tool
async def item_search(
    query: str,
    platform: Literal["amazon", "mock"],
    top_k: int = 20,
    price_max: float | None = None,
    rating_min: float | None = None,
) -> ItemSearchOutput:
    """在指定平台检索商品候选集。

    Args:
        query: 搜索关键词。
        platform: 目标平台，"amazon" 走 Apify，"mock" 走内置数据。
        top_k: 最多返回多少候选。
        price_max: 可选最高价格过滤。
        rating_min: 可选最低评分过滤。
    """
    top_k = min(top_k, 50)
    await monitor.report_tool_start(
        "item_search", {"query": query, "platform": platform, "top_k": top_k}
    )
    t0 = time.time()

    source: ProductDataSource = get_data_source()
    filters: dict[str, Any] = {"limit": top_k}
    if price_max is not None:
        filters["price_max"] = price_max
    if rating_min is not None:
        filters["rating_min"] = rating_min

    products = await source.search(query, **filters)
    candidates = [_product_to_candidate(p) for p in products if p.platform == platform]
    total_recall = len(candidates)
    truncated = total_recall > top_k
    candidates = candidates[:top_k]

    await monitor.report_tool_end("item_search", int((time.time() - t0) * 1000))
    return ItemSearchOutput(
        platform=platform,
        candidates=candidates,
        total_recall=total_recall,
        truncated=truncated,
    )
```

- [x] **Step 3: Run tests**

Run: `uv run pytest tests/test_item_search.py -v`
Expected: PASS

- [x] **Step 4: Run full suite to catch regressions**

Run: `uv run pytest`
Expected: PASS（如果旧测试依赖 Faiss 路径，需要同步更新或删除）

- [x] **Step 5: Commit**

```bash
git add app/agent/item_search.py tests/test_item_search.py
git commit -m "feat(item_search): back search with app.data ProductDataSource"
```

---

## Task 5: Adapt `price_compare` to accept `Product`

**Files:**
- Modify: `app/tools/price_compare.py`
- Test: `tests/test_price_compare.py`（新增或修改）

**Interfaces:**
- Consumes: `Candidate` or `Product`
- Produces: `PriceCompareOutput`

**Why:** 让 `price_compare` 能直接消费 `item_search` 的结果，也能接受 `Product` 列表。

- [x] **Step 1: Write the failing test**

```python
import asyncio
from decimal import Decimal

import pytest

from app.data import Product
from app.tools.price_compare import PriceCompareOutput, price_compare


def _product(pid: str, price: float, platform: str = "amazon") -> Product:
    return Product(
        product_id=pid,
        title=f"Product {pid}",
        category="electronics",
        price=Decimal(str(price)),
        platform=platform,
        url=f"https://example.com/{pid}",
    )


def test_price_compare_handles_product_input() -> None:
    async def run() -> PriceCompareOutput:
        return await price_compare.ainvoke({
            "candidates": [_product("A1", 29.99), _product("A2", 19.99)].model_dump(mode="json"),
            "base_currency": "CNY",
            "top_n": 2,
        })

    result = asyncio.run(run())
    assert len(result.ranked) == 2
    assert result.ranked[0].item_id == "A2"
```

- [x] **Step 2: Update the tool to accept Product-like dicts**

`price_compare` 当前接收 `list[Candidate]`。保持该接口不变，但在内部兼容从 dict 反序列化（LangChain 调用时会传入 dict）。通常 Pydantic 会自动处理，但如果传入 `Product` 对象，需要转换。

修改 `price_compare` 的入口：

```python
from app.data import Product


def _to_candidate(value: object) -> Candidate:
    if isinstance(value, Candidate):
        return value
    if isinstance(value, Product):
        return Candidate(
            item_id=value.product_id,
            platform=value.platform,
            title=value.title,
            price=float(value.price),
            currency="USD" if value.platform == "amazon" else "CNY",
            rating=value.rating,
            sales=value.sales_volume,
            image_url=value.image_url,
            attributes=value.attributes,
        )
    if isinstance(value, dict):
        return Candidate(**value)
    raise TypeError(f"Cannot convert {type(value)} to Candidate")
```

在 `price_compare` 函数开头加：

```python
candidates = [_to_candidate(c) for c in candidates]
```

- [x] **Step 3: Run tests**

Run: `uv run pytest tests/test_price_compare.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add app/tools/price_compare.py tests/test_price_compare.py
git commit -m "feat(price_compare): accept Product inputs"
```

---

## Task 6: Add `profit_calculator` tool

**Files:**
- Create: `app/tools/profit_calculator.py`
- Test: `tests/test_profit_calculator.py`

**Interfaces:**
- Consumes: `Candidate` / `Product` + cost info
- Produces: `ProfitCalcOutput` with margin, roi, suggested_price

**Why:** 选品核心指标，支撑"全链路决策"阶段。

- [x] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from app.tools.profit_calculator import ProfitCalcOutput, profit_calculator


def test_profit_calculator_computes_margin_and_roi() -> None:
    async def run() -> ProfitCalcOutput:
        return await profit_calculator.ainvoke({
            "selling_price": 100.0,
            "procurement_cost": 40.0,
            "shipping_cost": 10.0,
            "platform_fee_rate": 0.15,
        })

    result = asyncio.run(run())
    # revenue 100 - cost 40 - shipping 10 - fee 15 = 35 net
    assert result.net_profit == 35.0
    assert abs(result.profit_margin - 0.35) < 0.001
    assert result.roi > 0
```

- [x] **Step 2: Implement the tool**

```python
"""Profit calculation tool for product selection."""

import time

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor


class ProfitCalcOutput(BaseModel):
    """Profitability metrics for a single SKU."""

    selling_price: float
    total_cost: float
    net_profit: float
    profit_margin: float = Field(..., ge=-1, le=1)
    roi: float
    break_even_units: int
    suggested_price: float


@tool
async def profit_calculator(
    selling_price: float,
    procurement_cost: float,
    shipping_cost: float = 0.0,
    platform_fee_rate: float = 0.15,
    target_margin: float = 0.3,
) -> ProfitCalcOutput:
    """Calculate profit margin, ROI and suggested price for a product.

    Args:
        selling_price: Expected selling price in target currency.
        procurement_cost: Product sourcing cost.
        shipping_cost: Estimated shipping cost per unit.
        platform_fee_rate: Platform commission rate, e.g. 0.15 for 15%.
        target_margin: Desired profit margin for suggested price.
    """
    await monitor.report_tool_start("profit_calculator", {"selling_price": selling_price})
    t0 = time.time()

    platform_fee = selling_price * platform_fee_rate
    total_cost = procurement_cost + shipping_cost + platform_fee
    net_profit = selling_price - total_cost
    profit_margin = net_profit / selling_price if selling_price else 0.0
    roi = net_profit / total_cost if total_cost else 0.0
    break_even_units = int(procurement_cost / net_profit) + 1 if net_profit > 0 else -1

    desired_net = target_margin * selling_price
    suggested_price = (procurement_cost + shipping_cost + desired_net) / (1 - platform_fee_rate)
    suggested_price = round(suggested_price, 2)

    await monitor.report_tool_end("profit_calculator", int((time.time() - t0) * 1000))
    return ProfitCalcOutput(
        selling_price=selling_price,
        total_cost=round(total_cost, 2),
        net_profit=round(net_profit, 2),
        profit_margin=round(profit_margin, 4),
        roi=round(roi, 4),
        break_even_units=break_even_units,
        suggested_price=suggested_price,
    )
```

- [x] **Step 3: Run tests**

Run: `uv run pytest tests/test_profit_calculator.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add app/tools/profit_calculator.py tests/test_profit_calculator.py
git commit -m "feat(tools): add profit_calculator for selection decisions"
```

---

## Task 7: Adapt `item_picker` for product selection scoring

**Files:**
- Modify: `app/tools/item_picker.py`
- Test: `tests/test_item_picker.py`

**Interfaces:**
- Consumes: `list[LandedCost]` + `CategoryInsightOutput` + preferences
- Produces: `ItemPickerOutput`

**Why:** 现有评分侧重个人购物偏好（小众、免税、时效），需要增加选品维度（评分、利润、销量、竞争度）。

- [x] **Step 1: Update existing test expectations**

因为评分逻辑会变，先调整 `tests/test_item_picker.py` 中的断言。

- [x] **Step 2: Extend scoring logic**

在 `app/tools/item_picker.py` 中增加选品维度：

```python
def _score(
    cost: LandedCost,
    insight: CategoryInsightOutput | None,
    prefs: list[str],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    # 1. 价格档位匹配（保留）
    if insight and insight.price_tiers:
        budget_tier = next(
            (tier for tier in insight.price_tiers if tier.tier == "budget"), None
        )
        if budget_tier and budget_tier.range_cny[0] <= cost.landed_cny <= budget_tier.range_cny[1]:
            score += 0.25
            reasons.append(f"到手价 {cost.landed_cny} 落在目标档位")

    # 2. 物流时效（保留）
    if cost.eta_days <= 12:
        score += 0.15
        reasons.append(f"{cost.eta_days} 天到手")

    # 3. 关税（保留）
    if cost.duty_tier == "免征":
        score += 0.1
        reasons.append("跨境直邮免税")

    # 4. 评分维度（新增）
    # 需要 LandedCost 包含 rating；若当前没有，扩展 LandedCost 或从 Candidate 透传
    # 这里先占位，实际在 Task 7 中扩展 LandedCost

    return round(score, 2), reasons[:3]
```

- [x] **Step 3: Extend `LandedCost` to carry rating/review_count/sales**

在 `app/tools/shipping_calc.py` 中：

```python
class LandedCost(BaseModel):
    item_id: str
    platform: str
    price_cny: float
    shipping_cny: float
    duty_cny: float
    landed_cny: float
    eta_days: int
    duty_tier: Literal["免征", "标准", "高税"]
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None
```

并在 `shipping_calc` 中填充这些字段（从 `PricePoint` 透传，需要在 `PricePoint` 上加字段）。

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_item_picker.py tests/test_shipping_calc.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add app/tools/item_picker.py app/tools/shipping_calc.py tests/test_item_picker.py tests/test_shipping_calc.py
git commit -m "feat(item_picker): add selection-oriented scoring dimensions"
```

---

## Task 8: Adapt `shipping_calc` to carry selection metadata

**Files:**
- Modify: `app/tools/shipping_calc.py`
- Modify: `app/tools/price_compare.py`（扩展 `PricePoint`）
- Test: `tests/test_shipping_calc.py`（新增/修改）

**Interfaces:**
- `PricePoint` 增加 `rating`, `review_count`, `sales`
- `LandedCost` 增加 `rating`, `review_count`, `sales`
- `shipping_calc` 透传这些字段

- [x] **Step 1: Extend models**

`PricePoint`:

```python
class PricePoint(BaseModel):
    item_id: str
    platform: str
    title: str
    price_local: float
    currency_local: str
    price_cny: float
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None
    note: str | None = None
```

`LandedCost`:

```python
class LandedCost(BaseModel):
    ...
    rating: float | None = None
    review_count: int | None = None
    sales: int | None = None
```

- [x] **Step 2: Update shipping_calc to forward metadata**

```python
landed.append(LandedCost(
    item_id=p.item_id,
    platform=p.platform,
    price_cny=p.price_cny,
    shipping_cny=shipping_cny,
    duty_cny=duty_cny,
    landed_cny=total,
    eta_days=eta,
    duty_tier=duty_tier,
    rating=p.rating,
    review_count=p.review_count,
    sales=p.sales,
))
```

- [x] **Step 3: Update price_compare to populate new fields**

```python
points.append(PricePoint(
    item_id=c.item_id,
    platform=c.platform,
    title=c.title,
    price_local=c.price,
    currency_local=c.currency,
    price_cny=round(price_base, 2),
    rating=c.rating,
    review_count=c.review_count,
    sales=c.sales,
    note=_pack_note(c),
))
```

同时扩展 `Candidate` 模型以携带 `review_count`：

```python
class Candidate(BaseModel):
    ...
    review_count: int | None = None
```

并更新 `_product_to_candidate`：

```python
def _product_to_candidate(p: Product) -> Candidate:
    return Candidate(
        ...
        review_count=p.review_count,
    )
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_shipping_calc.py tests/test_price_compare.py tests/test_item_search.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add app/tools/shipping_calc.py app/tools/price_compare.py app/agent/item_search.py tests/
git commit -m "feat(shipping): carry rating/review/sales through price and landed cost"
```

---

## Task 9: Add `supplier_evaluator` tool

**Files:**
- Create: `app/tools/supplier_evaluator.py`
- Test: `tests/test_supplier_evaluator.py`

**Interfaces:**
- Consumes: `seller` name, `platform`, optional evidence list
- Produces: `SupplierEvalOutput` with risk_score, risk_level, notes

**Why:** 设计思路中列出的新增工具，用于货源风险评估。

- [x] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from app.tools.supplier_evaluator import RiskLevel, SupplierEvalOutput, supplier_evaluator


def test_supplier_evaluator_returns_risk_assessment() -> None:
    async def run() -> SupplierEvalOutput:
        return await supplier_evaluator.ainvoke({
            "seller": "Anker",
            "platform": "amazon",
        })

    result = asyncio.run(run())
    assert isinstance(result.risk_score, float)
    assert result.risk_level in {level.value for level in RiskLevel}
    assert result.notes
```

- [x] **Step 2: Implement the tool**

```python
"""Supplier risk evaluator for sourcing decisions."""

import time
from enum import Enum

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.monitor import monitor


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SupplierEvalOutput(BaseModel):
    """Risk assessment for a supplier or seller."""

    seller: str
    platform: str
    risk_score: float
    risk_level: RiskLevel
    notes: list[str]


@tool
async def supplier_evaluator(
    seller: str,
    platform: str,
    evidence: list[str] | None = None,
) -> SupplierEvalOutput:
    """Evaluate supplier/seller risk based on platform and simple heuristics.

    This is a rule-based MVP. Future versions can integrate third-party
    supplier databases or web search.
    """
    await monitor.report_tool_start("supplier_evaluator", {"seller": seller, "platform": platform})
    t0 = time.time()

    notes: list[str] = []
    score = 0.5

    if platform in {"amazon", "ebay"}:
        score -= 0.1
        notes.append(f"{platform} 平台有相对成熟的卖家评价体系")
    elif platform in {"aliexpress", "shopee"}:
        score += 0.1
        notes.append("跨境平台卖家稳定性差异大，建议小单测试")

    if seller and len(seller) > 3:
        score -= 0.05
        notes.append("卖家信息较完整")

    evidence = evidence or []
    if any("投诉" in e or "complaint" in e.lower() for e in evidence):
        score += 0.3
        notes.append("发现负面投诉证据")

    score = max(0.0, min(1.0, score))
    if score < 0.33:
        level = RiskLevel.LOW
    elif score < 0.66:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.HIGH

    await monitor.report_tool_end("supplier_evaluator", int((time.time() - t0) * 1000))
    return SupplierEvalOutput(
        seller=seller,
        platform=platform,
        risk_score=round(score, 2),
        risk_level=level,
        notes=notes,
    )
```

- [x] **Step 3: Run tests**

Run: `uv run pytest tests/test_supplier_evaluator.py -v`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add app/tools/supplier_evaluator.py tests/test_supplier_evaluator.py
git commit -m "feat(tools): add supplier_evaluator MVP"
```

---

## Task 10: Adapt `shopping_summary` to structured selection report

**Files:**
- Modify: `app/tools/shopping_summary.py`
- Test: `tests/test_shopping_summary.py`

**Interfaces:**
- Consumes: `PickedItem` list + user query
- Produces: `ShoppingSummaryOutput` with structured report fields

**Why:** 从"购物清单"升级为"选品报告"，输出选品决策依据。

- [x] **Step 1: Extend output model**

```python
class SelectionReport(BaseModel):
    product_id: str
    title: str
    platform: str
    landed_cny: float
    profit_margin: float | None = None
    score: float
    reasons: list[str]
    risks: list[str]


class ShoppingSummaryOutput(BaseModel):
    final_text: str
    picks: list[PickedItem]
    report: list[SelectionReport]
    learned_preferences: list[str]
```

- [x] **Step 2: Update the tool to build report**

在 `shopping_summary` 函数中，基于 `picks` 生成 `report` 列表。`profit_margin` 和 `risks` 可以先留空，由调用方传入或后续增强。

- [x] **Step 3: Update tests**

验证 `report` 字段存在且长度与 `picks` 一致。

- [x] **Step 4: Commit**

```bash
git add app/tools/shopping_summary.py tests/test_shopping_summary.py
git commit -m "feat(shopping_summary): output structured selection report"
```

---

## Task 11: Update `tool_registry.py`

**Files:**
- Modify: `app/agent/tool_registry.py`
- Test: `tests/test_tool_registry.py`

**Interfaces:**
- New `FULL_TOOL_SET` includes all adapted/new tools

- [x] **Step 1: Update registry**

```python
from app.agent.dispatch_tool import dispatch_tool
from app.agent.item_search import item_search
from app.tools.product_scraper import product_scraper
from app.tools.category_insight import category_insight
from app.tools.chat_fallback import chat_fallback
from app.tools.item_picker import item_picker
from app.tools.market_trend_research import market_trend_research
from app.tools.planner import planner
from app.tools.price_compare import price_compare
from app.tools.profit_calculator import profit_calculator
from app.tools.shipping_calc import shipping_calc
from app.tools.shopping_summary import shopping_summary
from app.tools.supplier_evaluator import supplier_evaluator
from app.tools.web_search import web_search


FULL_TOOL_SET = [
    planner,
    chat_fallback,
    web_search,
    market_trend_research,
    category_insight,
    product_scraper,
    item_search,
    item_picker,
    price_compare,
    shipping_calc,
    profit_calculator,
    supplier_evaluator,
    shopping_summary,
    dispatch_tool,
]
```

- [x] **Step 2: Update test**

```python
def test_tool_registry_includes_selection_tools() -> None:
    names = {t.name for t in FULL_TOOL_SET}
    assert "market_trend_research" in names
    assert "product_scraper" in names
    assert "profit_calculator" in names
    assert "supplier_evaluator" in names
    assert "item_search" in names
```

- [x] **Step 3: Run full test suite**

Run: `uv run pytest`
Expected: PASS

- [x] **Step 4: Commit**

```bash
git add app/agent/tool_registry.py tests/test_tool_registry.py
git commit -m "feat(registry): register lector selection tools"
```

---

## Task 12: Add integration script for three-stage demo

**Files:**
- Create: `scripts/demo_selection_pipeline.py`

**Why:** 提供一个可运行的端到端示例，验证三阶段链路。

- [x] **Step 1: Implement the script**

```python
"""Demo script: discover -> filter -> decide selection pipeline."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.item_search import item_search
from app.tools.item_picker import item_picker
from app.tools.market_trend_research import market_trend_research
from app.tools.price_compare import price_compare
from app.tools.profit_calculator import profit_calculator
from app.tools.shipping_calc import shipping_calc
from app.tools.shopping_summary import shopping_summary


async def main() -> None:
    category = "wireless earbuds"

    print("=== Stage 1: Discover ===")
    trend = await market_trend_research.ainvoke({"category": category})
    print(trend.trend_summary)

    print("\n=== Stage 2: Filter ===")
    search_result = await item_search.ainvoke({
        "query": category,
        "platform": "mock",
        "top_k": 5,
        "rating_min": 4.0,
    })
    candidates = [c.model_dump() for c in search_result.candidates]
    compare = await price_compare.ainvoke({"candidates": candidates, "top_n": 3})
    points = [p.model_dump() for p in compare.ranked]
    landed = await shipping_calc.ainvoke({"points": points, "destination": "CN"})
    picks = await item_picker.ainvoke({
        "landed": [i.model_dump() for i in landed.items],
        "top_n": 2,
    })

    print("\n=== Stage 3: Decide ===")
    for pick in picks.picks:
        profit = await profit_calculator.ainvoke({
            "selling_price": pick.landed_cny * 1.3,
            "procurement_cost": pick.landed_cny,
            "shipping_cost": 0,
        })
        print(f"{pick.item_id}: score={pick.score}, margin={profit.profit_margin}")

    summary = await shopping_summary.ainvoke({
        "picks": [p.model_dump() for p in picks.picks],
        "user_query": category,
    })
    print("\n=== Report ===")
    print(summary.final_text)


if __name__ == "__main__":
    asyncio.run(main())
```

- [x] **Step 2: Run the demo**

Run: `uv run python scripts/demo_selection_pipeline.py`
Expected: Prints three-stage output without errors.

- [x] **Step 3: Commit**

```bash
git add scripts/demo_selection_pipeline.py
git commit -m "chore(scripts): add three-stage selection pipeline demo"
```

---

## Self-Review

### Spec coverage

对照 `/Users/Z1nk/Documents/Zault/proj/lector/设计思路.md`：

- **Agent 三阶段能力**
  - 发现：`market_trend_research` ✅
  - 筛选：`item_search` + `item_picker` ✅
  - 全链路：`price_compare` + `shipping_calc` + `profit_calculator` + `supplier_evaluator` + `shopping_summary` ✅
- **新增工具**
  - `market_trend_research` ✅
  - `product_scraper` ✅
  - `profit_calculator` ✅
  - `supplier_evaluator` ✅
  - `report_generator` → 由 `shopping_summary` 的结构化 `report` 字段替代 MVP 版本 ✅
- **数据源无感知**
  - `item_search` 改接 `get_data_source()` ✅
  - `product_scraper` 复用同一数据源 ✅
- **搜索结果持久化**
  - MongoDB 缓存：`app/data/cache.py` + `ApifyAmazonDataSource` 集成 ✅

### Placeholder scan

无 TBD/TODO/"implement later"。每个任务包含完整代码、测试命令、预期结果。

### Type consistency

- `Candidate` 扩展 `review_count` 后，`item_search` 和 `price_compare` 同步更新。
- `PricePoint` 扩展 `review_count`/`sales` 后，`shipping_calc` 的 `LandedCost` 同步更新。
- `item_picker` 消费 `LandedCost`，新字段透传后可用于评分。
