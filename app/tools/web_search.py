"""Web search routed through the active model provider's built-in tools."""

import os
import time
from typing import Any, Literal, Protocol

import httpx
from langchain_core.tools import tool
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.api.monitor import monitor


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float | None = None


class WebSearchOutput(BaseModel):
    query: str
    provider: str
    status: Literal["ok", "unavailable"]
    results: list[SearchResult] = Field(default_factory=list)
    error: str | None = None

    def as_evidence(self, max_chars: int = 6000) -> str:
        blocks = [
            f"[{index}] {result.title}\nURL: {result.url}\n{result.content}"
            for index, result in enumerate(self.results, start=1)
        ]
        return "\n\n".join(blocks)[:max_chars]


class BuiltInWebSearchBackend(Protocol):
    async def search(self, query: str, *, max_results: int) -> WebSearchOutput: ...


class UnavailableWebSearchBackend:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def search(self, query: str, *, max_results: int) -> WebSearchOutput:
        del max_results
        return WebSearchOutput(
            query=query,
            provider="unavailable",
            status="unavailable",
            error=self._reason,
        )


class DeepSeekAnthropicWebSearchBackend:
    """DeepSeek 原生 Web Search 的 Anthropic Messages 协议适配器。"""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.deepseek.com/anthropic",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/v1/messages"
        self._client = client

    @staticmethod
    def _unavailable(query: str, error: str) -> WebSearchOutput:
        return WebSearchOutput(
            query=query,
            provider="deepseek_anthropic",
            status="unavailable",
            error=error,
        )

    @staticmethod
    def _map_results(
        query: str,
        payloads: list[dict[str, Any]],
        max_results: int,
    ) -> WebSearchOutput:
        texts: list[str] = []
        raw_results: list[dict[str, Any]] = []
        for payload in payloads:
            content = payload.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    texts.append(str(block["text"]))
                    continue
                if block.get("type") != "web_search_tool_result":
                    continue
                search_content = block.get("content", [])
                if not isinstance(search_content, list):
                    continue
                raw_results.extend(
                    item
                    for item in search_content
                    if isinstance(item, dict)
                    and item.get("type") == "web_search_result"
                )

        summary = "\n".join(texts).strip()
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for item in raw_results:
            url = str(item.get("url") or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                SearchResult(
                    title=str(item.get("title") or url),
                    url=url,
                    content=summary,
                )
            )
            if len(results) >= max(1, max_results):
                break

        if not results:
            return DeepSeekAnthropicWebSearchBackend._unavailable(
                query,
                "DeepSeek web search returned no URL results",
            )
        return WebSearchOutput(
            query=query,
            provider="deepseek_anthropic",
            status="ok",
            results=results,
        )

    async def search(self, query: str, *, max_results: int) -> WebSearchOutput:
        client = self._client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._client is None
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": query}
        ]
        payloads: list[dict[str, Any]] = []
        try:
            for attempt in range(2):
                response = await client.post(
                    self._endpoint,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "max_tokens": 2048,
                        "tools": [
                            {
                                "type": "web_search_20250305",
                                "name": "web_search",
                                "max_uses": 1,
                            }
                        ],
                        "messages": messages,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("DeepSeek response is not an object")
                payloads.append(payload)
                if payload.get("stop_reason") != "pause_turn" or attempt == 1:
                    break
                content = payload.get("content")
                if not isinstance(content, list):
                    break
                messages.append({"role": "assistant", "content": content})
            return self._map_results(query, payloads, max_results)
        except httpx.HTTPStatusError as exc:
            return self._unavailable(
                query,
                f"DeepSeek web search failed: HTTP {exc.response.status_code}",
            )
        except Exception as exc:
            return self._unavailable(
                query,
                f"DeepSeek web search failed: {type(exc).__name__}",
            )
        finally:
            if owns_client:
                await client.aclose()


class OpenAIResponsesWebSearchBackend:
    def __init__(self, *, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    async def search(self, query: str, *, max_results: int) -> WebSearchOutput:
        try:
            response = await self._client.responses.create(
                model=self._model,
                tools=[{"type": "web_search"}],
                input=query,
            )
            payload = response.model_dump()
            output_text = str(getattr(response, "output_text", ""))
            results: list[SearchResult] = []
            seen_urls: set[str] = set()
            for item in payload.get("output", []):
                if not isinstance(item, dict):
                    continue
                for content in item.get("content", []):
                    if not isinstance(content, dict):
                        continue
                    text = str(content.get("text") or output_text)
                    for annotation in content.get("annotations", []):
                        if not isinstance(annotation, dict):
                            continue
                        if annotation.get("type") != "url_citation":
                            continue
                        url = str(annotation.get("url", ""))
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        results.append(
                            SearchResult(
                                title=str(annotation.get("title") or url),
                                url=url,
                                content=text,
                            )
                        )
                        if len(results) >= max_results:
                            break
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
            if not results:
                return WebSearchOutput(
                    query=query,
                    provider="openai_responses",
                    status="unavailable",
                    error="Built-in web search returned no URL citations",
                )
            return WebSearchOutput(
                query=query,
                provider="openai_responses",
                status="ok",
                results=results,
            )
        except Exception as exc:
            return WebSearchOutput(
                query=query,
                provider="openai_responses",
                status="unavailable",
                error=f"Built-in web search failed: {type(exc).__name__}",
            )


def get_web_search_backend() -> BuiltInWebSearchBackend:
    backend = os.environ.get("LLM_WEB_SEARCH_BACKEND", "auto").strip().lower()
    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    if backend == "auto":
        lowered_base_url = base_url.lower()
        if "api.openai.com" in lowered_base_url:
            backend = "openai_responses"
        elif "api.deepseek.com" in lowered_base_url:
            backend = "deepseek_anthropic"
        else:
            backend = "none"
    if backend == "none":
        return UnavailableWebSearchBackend(
            "The active model endpoint has no configured built-in web search capability"
        )
    if backend not in {"deepseek_anthropic", "openai_responses"}:
        return UnavailableWebSearchBackend(
            f"Unknown built-in web search backend: {backend}"
        )
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        return UnavailableWebSearchBackend(
            "LLM_API_KEY is required for built-in web search"
        )
    if backend == "deepseek_anthropic":
        return DeepSeekAnthropicWebSearchBackend(
            api_key=api_key,
            model=os.environ.get("LLM_MODEL_NAME", "deepseek-v4-pro"),
            base_url=os.environ.get(
                "DEEPSEEK_ANTHROPIC_BASE_URL",
                "https://api.deepseek.com/anthropic",
            ),
        )
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return OpenAIResponsesWebSearchBackend(
        client=client,
        model=os.environ.get("LLM_MODEL_NAME", "gpt-5"),
    )


@tool
async def web_search(query: str, max_results: int = 5) -> WebSearchOutput:
    """Search the web with the active model provider's built-in search tool."""
    max_results = max(1, min(max_results, 10))
    await monitor.report_tool_start(
        "web_search", {"query": query, "max_results": max_results}
    )
    started_at = time.time()
    result = await get_web_search_backend().search(
        query, max_results=max_results
    )
    await monitor.report_tool_end("web_search", int((time.time() - started_at) * 1000))
    return result
