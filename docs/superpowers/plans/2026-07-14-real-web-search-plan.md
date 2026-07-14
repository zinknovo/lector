# Real Web Search and Unified FX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder search tool with Tavily-backed structured search and make trend, exchange-rate and price comparison use it consistently.

**Architecture:** `web_search` owns provider IO and returns a stable Pydantic model. Consumers receive structured evidence; exchange-rate caching remains in `exchange_rate`, and `price_compare` awaits that tool instead of reading a static table.

**Tech Stack:** Python 3.11+, httpx, LangChain tools, Pydantic v2, pytest.

## Global Constraints

- Missing external configuration must not break Mock/CI flows.
- Never fabricate search results or exchange rates.
- Use existing `httpx`; add no search SDK dependency.
- Every behavior change follows RED-GREEN and full pytest verification.

### Task 1: Tavily-backed web search

**Files:** Modify `app/tools/web_search.py`, create `tests/test_web_search.py`, modify `.env.example`.

- [ ] Add failing tests for successful result mapping and missing-key unavailable output.
- [ ] Run `uv run pytest tests/test_web_search.py -v` and confirm RED.
- [ ] Add `SearchResult`, `WebSearchOutput`, `_search_tavily`, injectable `httpx.AsyncClient`, timeouts and monitor events.
- [ ] Run focused and full pytest; commit `feat: connect Tavily web search`.

### Task 2: Structured search consumers

**Files:** Modify `app/tools/market_trend_research.py`, `app/tools/exchange_rate.py`, corresponding tests.

- [ ] Add failing tests proving URLs/content reach LLM evidence and unavailable search prevents rate parsing.
- [ ] Implement one evidence formatter on `WebSearchOutput` and use it in both consumers.
- [ ] Run focused and full pytest; commit `feat: consume structured search evidence`.

### Task 3: Dynamic FX in price comparison

**Files:** Modify `app/tools/price_compare.py`, `tests/test_price_compare.py`, README.

- [ ] Add a failing USD/CNY conversion test with a mocked exchange-rate invocation.
- [ ] Replace synchronous static `to_base` calls with per-currency awaited rates to the requested base currency.
- [ ] Document `TAVILY_API_KEY`; run backend, frontend, build and Demo verification.
- [ ] Commit, merge to main and push.

## Self-Review

- All spec behaviors map to one task.
- No new dependency or provider-specific type leaks into consumers.
- `WebSearchOutput` is the only cross-task search interface.
