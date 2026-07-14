# DeepSeek Native Web Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Lector's existing `web_search` tool use DeepSeek's native server-side web search through the DeepSeek Anthropic-compatible Messages API.

**Architecture:** Keep the existing `BuiltInWebSearchBackend` boundary and all normal LLM calls unchanged. Add one HTTPX-based DeepSeek adapter that posts Anthropic Messages payloads, parses server search-result blocks into `WebSearchOutput`, and is selected automatically for official DeepSeek endpoints.

**Tech Stack:** Python 3.11+, HTTPX, Pydantic, LangChain async tools, pytest.

## Global Constraints

- Reuse `LLM_API_KEY` and `LLM_MODEL_NAME`; do not add Tavily, another search provider, or the Anthropic SDK.
- Keep ordinary inference on the current DeepSeek OpenAI Chat Completions path.
- Default search protocol root is `https://api.deepseek.com/anthropic`, overridable with `DEEPSEEK_ANTHROPIC_BASE_URL`.
- Never expose API keys or full failed response bodies in errors, logs, or tests.
- Keep the public `web_search` input/output models and downstream tool contracts unchanged.
- Run focused tests after each red/green cycle and full `uv run pytest` after each task.
- Do not modify or commit `.idea` files.

---

### Task 1: Add the DeepSeek Anthropic search adapter

**Files:**
- Modify: `app/tools/web_search.py`
- Modify: `tests/test_web_search.py`

**Interfaces:**
- Consumes: `SearchResult`, `WebSearchOutput`, `BuiltInWebSearchBackend`.
- Produces: `DeepSeekAnthropicWebSearchBackend(client, model, api_key, base_url)` implementing `search(query, max_results)`.

- [ ] **Step 1: Write failing adapter tests**

Add an `httpx.MockTransport` fixture and tests that specify the complete request and response mapping:

```python
def test_deepseek_backend_uses_server_search_and_maps_results() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "srvtoolu_1",
                    "content": [
                        {"type": "web_search_result", "title": "A", "url": "https://a.test", "encrypted_content": "opaque"},
                        {"type": "web_search_result", "title": "A duplicate", "url": "https://a.test", "encrypted_content": "opaque"},
                        {"type": "web_search_result", "title": "B", "url": "https://b.test", "encrypted_content": "opaque"},
                    ],
                },
                {"type": "text", "text": "Current market evidence."},
            ],
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = DeepSeekAnthropicWebSearchBackend(
        client=client,
        model="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.test/anthropic",
    )
    result = asyncio.run(backend.search("earbuds trend", max_results=1))
    asyncio.run(client.aclose())

    payload = json.loads(requests[0].content)
    assert requests[0].url == "https://api.deepseek.test/anthropic/v1/messages"
    assert requests[0].headers["x-api-key"] == "test-key"
    assert requests[0].headers["anthropic-version"] == "2023-06-01"
    assert payload["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    assert result.provider == "deepseek_anthropic"
    assert [item.url for item in result.results] == ["https://a.test"]
    assert result.results[0].content == "Current market evidence."
```

Add separate tests for one `pause_turn` continuation and safe HTTP failure:

```python
def test_deepseek_backend_continues_pause_turn_once() -> None:
    # First response returns pause_turn plus a search result; second returns final text.
    # Assert two requests and that request 2 appends the first response as assistant content.


def test_deepseek_backend_redacts_http_failure() -> None:
    # Return HTTP 401 with a body containing "secret-response".
    # Assert status=unavailable, error contains "HTTP 401", and excludes the response body and API key.
```

- [ ] **Step 2: Run tests and verify the adapter is missing**

Run: `uv run pytest tests/test_web_search.py -q`

Expected: collection fails because `DeepSeekAnthropicWebSearchBackend` is not defined.

- [ ] **Step 3: Implement request, continuation, and parsing**

In `app/tools/web_search.py`, import `httpx` and implement:

```python
class DeepSeekAnthropicWebSearchBackend:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.deepseek.com/anthropic",
        client: httpx.AsyncClient | None = None,
    ) -> None: ...

    async def search(self, query: str, *, max_results: int) -> WebSearchOutput:
        # POST /v1/messages with max_tokens=2048 and web_search_20250305.
        # If stop_reason is pause_turn, append assistant content and retry exactly once.
        # Parse URLs from all response payloads and summary text from the last text blocks.
        # Deduplicate URLs, apply max_results, and return provider=deepseek_anthropic.
```

Use an injected client without closing it. When no client is injected, create an `httpx.AsyncClient` with a 120-second default inside `search()` and close it in `finally`. The factory reads `DEEPSEEK_WEB_SEARCH_TIMEOUT_SECONDS`; live verification found that a valid DeepSeek search can take about 45 seconds. Call `raise_for_status()`. Map `HTTPStatusError` to `DeepSeek web search failed: HTTP <status>` and all other exceptions to `DeepSeek web search failed: <ExceptionType>`.

Only accept dictionary content blocks. Ignore error blocks, empty URLs, `encrypted_content`, and malformed entries. If no URL remains, return unavailable with `DeepSeek web search returned no URL results`.

- [ ] **Step 4: Run focused and full tests**

Run: `uv run pytest tests/test_web_search.py -q`

Expected: all web-search tests pass.

Run: `uv run pytest -q`

Expected: full suite passes.

- [ ] **Step 5: Commit the adapter**

```bash
git add app/tools/web_search.py tests/test_web_search.py
git commit -m "feat: add DeepSeek native web search backend"
```

### Task 2: Route DeepSeek automatically and update readiness/configuration

**Files:**
- Modify: `app/tools/web_search.py`
- Modify: `app/integrations/readiness.py`
- Modify: `tests/test_web_search.py`
- Modify: `tests/test_readiness.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/production-readiness.md`

**Interfaces:**
- Consumes: `DeepSeekAnthropicWebSearchBackend` from Task 1.
- Produces: factory modes `auto|openai_responses|deepseek_anthropic|none` and readiness behavior consistent with the factory.

- [ ] **Step 1: Write failing factory and readiness tests**

Replace the old unavailable assertion with:

```python
def test_auto_backend_selects_deepseek_anthropic(monkeypatch) -> None:
    monkeypatch.setenv("LLM_WEB_SEARCH_BACKEND", "auto")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL_NAME", "deepseek-v4-pro")

    backend = get_web_search_backend()

    assert isinstance(backend, DeepSeekAnthropicWebSearchBackend)
```

Also assert explicit `deepseek_anthropic` works with a proxy LLM base URL and honors `DEEPSEEK_ANTHROPIC_BASE_URL`. In readiness tests, patch `web_search.ainvoke` to return an OK result and assert `_check_web_search()` does not skip when `LLM_WEB_SEARCH_BACKEND=auto` and the base URL is DeepSeek.

- [ ] **Step 2: Run tests and verify old routing fails**

Run: `uv run pytest tests/test_web_search.py tests/test_readiness.py -q`

Expected: DeepSeek auto-routing and readiness tests fail because auto still maps DeepSeek to none.

- [ ] **Step 3: Implement routing and readiness**

Update `get_web_search_backend()`:

```python
if backend == "auto":
    if "api.openai.com" in base_url.lower():
        backend = "openai_responses"
    elif "api.deepseek.com" in base_url.lower():
        backend = "deepseek_anthropic"
    else:
        backend = "none"
```

For the DeepSeek branch, require `LLM_API_KEY`, reuse `LLM_MODEL_NAME` with default `deepseek-v4-pro`, and read `DEEPSEEK_ANTHROPIC_BASE_URL` with the official default. Preserve the existing OpenAI branch unchanged.

Update `_check_web_search()` so auto considers both official OpenAI and DeepSeek endpoints configured; explicit `none` still skips, runtime unavailable still fails.

- [ ] **Step 4: Update active documentation and configuration**

- Add `DEEPSEEK_ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` to `.env.example` as an optional override.
- Replace README text saying DeepSeek built-in search is unavailable with the two-protocol routing explanation.
- Update production readiness docs to list DeepSeek auto support and the same-key behavior.

- [ ] **Step 5: Run focused/full verification and commit**

Run: `uv run pytest tests/test_web_search.py tests/test_readiness.py tests/test_market_trend_research.py tests/test_exchange_rate.py -q`

Expected: all pass.

Run: `uv run pytest -q && uv run basedpyright`

Expected: all tests pass and type checker reports 0 errors.

Commit:

```bash
git add app/tools/web_search.py app/integrations/readiness.py tests/test_web_search.py tests/test_readiness.py .env.example README.md docs/production-readiness.md
git commit -m "feat: route DeepSeek through native web search"
```

### Task 3: Verify the real DeepSeek search path and complete delivery

**Files:**
- Modify only if live verification reveals a reproducible protocol mismatch; any fix must start with a failing regression test in `tests/test_web_search.py`.

**Interfaces:**
- Consumes: final backend and current ignored `.env` DeepSeek credentials.
- Produces: evidence that the real endpoint returns at least one cited URL without exposing secrets.

- [ ] **Step 1: Run a live smoke through the public tool**

Run a short Python expression that loads `.env`, invokes:

```python
result = asyncio.run(
    web_search.ainvoke({"query": "Amazon ecommerce trends 2026", "max_results": 2})
)
assert result.status == "ok", result.error
assert result.provider == "deepseek_anthropic"
assert result.results and all(item.url.startswith("http") for item in result.results)
print(result.provider, len(result.results), [item.url for item in result.results])
```

Expected: provider `deepseek_anthropic`, one or two HTTP URLs, no key or full content printed.

- [ ] **Step 2: Run complete local verification**

Run separately:

```bash
uv run pytest -q
uv run basedpyright
uv run python scripts/demo_selection_pipeline.py
docker compose config --services
docker compose up -d --build
docker compose ps
```

Expected: Python tests and type checking pass, demo exits 0, and exactly MongoDB/Agent/Gateway/Frontend are running.

- [ ] **Step 3: Inspect and deliver**

Run `rtk git diff --check`, inspect `main...HEAD`, confirm `.idea` is absent from commits, merge to `main`, re-run Python tests on merged `main`, remove the owned worktree, delete the feature branch, and push `main` to `origin`.
