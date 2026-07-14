"""Strict, independently reported checks for Lector external capabilities."""

import asyncio
import math
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.data import ApifyAmazonDataSource, Product
from app.data.cache import ProductSearchCache

AsyncCheck = Callable[[], Awaitable[str]]


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    detail: str
    duration_ms: int


class ReadinessReport(BaseModel):
    checks: list[CheckResult]

    @property
    def exit_code(self) -> int:
        return 1 if any(item.status == CheckStatus.FAIL for item in self.checks) else 0


class CapabilitySkipped(RuntimeError):
    """Raised when a capability has no local configuration."""


def _configured(value: str | None) -> bool:
    if not value or len(value.strip()) < 8:
        return False
    lowered = value.lower()
    return not any(
        marker in lowered for marker in ("your-", "replace", "placeholder", "example")
    )


def _native_timeout_seconds(cap: float = 3.0) -> float:
    readiness_timeout = float(os.environ.get("READINESS_TIMEOUT_SECONDS", "30"))
    return max(0.1, min(cap, readiness_timeout * 0.8))


def _redact(detail: str, secrets: Sequence[str]) -> str:
    redacted = detail
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted[:500]


def _validate_vector(vector: list[float]) -> str:
    if len(vector) != 1024:
        raise ValueError(f"expected 1024 dimensions, received {len(vector)}")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
        raise ValueError("embedding contains non-finite values")
    return "1024-dimensional vector"


async def _check_apify(api_token: str | None = None) -> str:
    token = api_token or os.environ.get("APIFY_API_TOKEN")
    if not _configured(token):
        raise CapabilitySkipped("APIFY_API_TOKEN is not configured")
    timeout = float(os.environ.get("READINESS_TIMEOUT_SECONDS", "30"))
    source = ApifyAmazonDataSource(
        api_token=token,
        request_timeout_seconds=max(1.0, timeout * 0.8),
        max_retries=1,
        use_cache=False,
    )
    products = await source.search("wireless earbuds", max_results=1, limit=1)
    amazon = [item for item in products if item.platform == "amazon"]
    if not amazon:
        raise RuntimeError("Apify returned no normalized Amazon products")
    return f"{len(amazon)} Amazon product ({amazon[0].product_id})"


async def _check_mongodb() -> str:
    url = os.environ.get("MONGODB_URL")
    if not _configured(url):
        raise CapabilitySkipped("MONGODB_URL is not configured")

    def round_trip() -> str:
        from pymongo import MongoClient

        timeout_ms = int(_native_timeout_seconds() * 1000)
        client = MongoClient(
            url,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms,
            socketTimeoutMS=timeout_ms,
        )
        try:
            client.admin.command("ping")
            collection = client["lector"]["product_search_cache"]
            cache = ProductSearchCache(collection=collection)
            query = f"readiness-{uuid.uuid4().hex}"
            product = Product(
                product_id="readiness",
                title="Readiness Probe",
                category="health_check",
                price=Decimal("1.00"),
                platform="amazon",
                url="https://example.invalid/readiness",
            )
            cache.set("readiness", query, {}, [product])
            cached = cache.get("readiness", query, {})
            collection.delete_one(
                {"_id": ProductSearchCache._key("readiness", query, {})}
            )
            if not cached or cached[0].product_id != "readiness":
                raise RuntimeError("MongoDB cache round-trip failed")
            return "ping and cache round-trip"
        finally:
            client.close()

    return await asyncio.to_thread(round_trip)


async def _check_llm() -> str:
    if not _configured(os.environ.get("LLM_API_KEY")):
        raise CapabilitySkipped("LLM_API_KEY is not configured")
    from app.tools.planner import planner

    result = await planner.ainvoke({"query": "发现美国无线耳机潜力品类"})
    return f"structured planner intent={result.intent}"


async def _check_web_search() -> str:
    from app.tools.web_search import web_search

    backend = os.environ.get("LLM_WEB_SEARCH_BACKEND", "auto").lower()
    base_url = os.environ.get("LLM_BASE_URL", "").lower()
    if backend == "none" or (backend == "auto" and "api.openai.com" not in base_url):
        raise CapabilitySkipped("active LLM endpoint has no configured built-in search")
    result = await web_search.ainvoke({"query": "Amazon ecommerce trend today", "max_results": 1})
    if result.status != "ok" or not result.results:
        raise RuntimeError(result.error or "built-in search returned no evidence")
    return f"{len(result.results)} cited result"


async def _check_opensearch() -> str:
    host = os.environ.get("OPENSEARCH_HOST")
    if not host:
        raise CapabilitySkipped("OPENSEARCH_HOST is not configured")

    def cluster_health() -> str:
        from opensearchpy import OpenSearch

        user = os.environ.get("OPENSEARCH_USER")
        password = os.environ.get("OPENSEARCH_PASS")
        auth = (user, password) if user and password else None
        client = OpenSearch(
            hosts=[{"host": host, "port": int(os.environ.get("OPENSEARCH_PORT", "9200"))}],
            http_auth=auth,
            use_ssl=False,
            timeout=_native_timeout_seconds(),
        )
        try:
            health: dict[str, Any] = client.cluster.health()
            return f"cluster status={health.get('status', 'unknown')}"
        finally:
            client.close()

    return await asyncio.to_thread(cluster_health)


async def _check_tower() -> str:
    if not os.environ.get("TOWER_QUERY_ENDPOINT"):
        raise CapabilitySkipped("TOWER_QUERY_ENDPOINT is not configured")
    from app.recall.towers import TowerClient

    client = TowerClient()
    try:
        vector = await client.encode_query("wireless earbuds")
        return _validate_vector(vector)
    finally:
        await client.client.aclose()


def _production_checks() -> dict[str, AsyncCheck]:
    return {
        "apify": _check_apify,
        "mongodb": _check_mongodb,
        "llm": _check_llm,
        "web_search": _check_web_search,
        "opensearch": _check_opensearch,
        "tower": _check_tower,
    }


async def run_readiness(
    selected: set[str],
    *,
    checks: Mapping[str, AsyncCheck] | None = None,
    secrets: Sequence[str] = (),
    timeout_seconds: float | None = None,
) -> ReadinessReport:
    available = dict(checks or _production_checks())
    unknown = selected - available.keys()
    if unknown:
        raise ValueError(f"unknown readiness checks: {', '.join(sorted(unknown))}")
    results: list[CheckResult] = []
    deadline = timeout_seconds or float(
        os.environ.get("READINESS_TIMEOUT_SECONDS", "30")
    )
    if deadline <= 0:
        raise ValueError("readiness timeout must be positive")
    for name in sorted(selected):
        started = time.perf_counter()
        try:
            async with asyncio.timeout(deadline):
                detail = await available[name]()
            status = CheckStatus.PASS
        except CapabilitySkipped as exc:
            status = CheckStatus.SKIPPED
            detail = str(exc)
        except Exception as exc:
            status = CheckStatus.FAIL
            detail = f"{type(exc).__name__}: {exc}"
        results.append(
            CheckResult(
                name=name,
                status=status,
                detail=_redact(detail, secrets),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        )
    return ReadinessReport(checks=results)
