"""Structured web search backed by Tavily."""

import os
import time
from typing import Any, Literal

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.api.monitor import monitor


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float | None = None


class WebSearchOutput(BaseModel):
    query: str
    provider: str = "tavily"
    status: Literal["ok", "unavailable"]
    results: list[SearchResult] = Field(default_factory=list)
    error: str | None = None

    def as_evidence(self, max_chars: int = 6000) -> str:
        """Render bounded, source-attributed evidence for an LLM prompt."""
        blocks = [
            f"[{index}] {result.title}\nURL: {result.url}\n{result.content}"
            for index, result in enumerate(self.results, start=1)
        ]
        return "\n\n".join(blocks)[:max_chars]


async def _search_tavily(
    query: str,
    *,
    max_results: int,
    api_key: str,
    base_url: str,
    client: httpx.AsyncClient | None = None,
) -> WebSearchOutput:
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    try:
        response = await active_client.post(
            f"{base_url.rstrip('/')}/search",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("Tavily response.results must be a list")
        results = [
            SearchResult(
                title=str(item.get("title", "Untitled")),
                url=str(item.get("url", "")),
                content=str(item.get("content", "")),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in raw_results
            if isinstance(item, dict) and item.get("url")
        ]
        return WebSearchOutput(query=query, status="ok", results=results)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return WebSearchOutput(
            query=query,
            status="unavailable",
            error=f"Tavily search failed: {type(exc).__name__}",
        )
    finally:
        if owns_client:
            await active_client.aclose()


@tool
async def web_search(query: str, max_results: int = 5) -> WebSearchOutput:
    """Search the public web and return source-attributed results."""
    max_results = max(1, min(max_results, 10))
    await monitor.report_tool_start(
        "web_search", {"query": query, "max_results": max_results}
    )
    started_at = time.time()
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        result = WebSearchOutput(
            query=query,
            status="unavailable",
            error="TAVILY_API_KEY is not configured",
        )
    else:
        result = await _search_tavily(
            query,
            max_results=max_results,
            api_key=api_key,
            base_url=os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com"),
        )
    await monitor.report_tool_end("web_search", int((time.time() - started_at) * 1000))
    return result
