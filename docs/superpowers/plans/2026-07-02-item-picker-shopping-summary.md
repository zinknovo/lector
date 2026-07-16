# ItemPicker, ShoppingSummary, ForkGuard, and Middleware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add deterministic item selection, LLM-generated shopping output, fork-depth protection, long tool-result truncation, repeated-tool loop detection, and register all seven implemented tools in `FULL_TOOL_SET`.

**Architecture:** `item_picker` consumes `LandedCost` plus optional category insight and preferences, applies hard filters, computes a deterministic score, and returns Pydantic output. `shopping_summary` consumes selected items, calls the shared LLM with the existing summary prompt, and returns the final text plus learned preferences. `fork_guard` uses a `ContextVar` to cap recursive Subagent dispatch at depth two; `dispatch_tool` lazily imports the registry to avoid a circular import. The existing tool registry remains the single source of truth.

**Tech Stack:** Python 3.11, Pydantic, LangChain tools, pytest, basedpyright

---

### Task 1: ItemPicker behavior

**Files:**
- Create: `tests/test_item_picker.py`
- Create: `app/tools/item_picker.py`

- [x] **Step 1: Write failing tests**

Create tests that construct `LandedCost` and `CategoryInsightOutput` values and assert:

```python
assert _check_preferences(plastic_cost, ["不要塑料"]) == [
    "HARD_FAIL:塑料，命中用户黑名单"
]
assert _score(preferred_cost, insight, ["偏好小众"]) == (
    1.0,
    ["到手价 199.0 落在中档 budget", "10 天到手", "跨境直邮免税"],
)
```

Add an async tool test asserting hard-filtered items are omitted, candidates are sorted descending, `top_n` is honored, and rejection summaries are returned.

- [x] **Step 2: Verify RED**

Run: `rtk test uv run pytest tests/test_item_picker.py -q`

Expected: collection fails because `app.tools.item_picker` does not exist.

- [x] **Step 3: Implement the tool**

Create `PickedItem` and `ItemPickerOutput`, then implement:

```python
def _check_preferences(cost: LandedCost, prefs: list[str]) -> list[str]:
    flags: list[str] = []
    if any("不要塑料" in pref for pref in prefs):
        if cost.platform == "ebay" and cost.item_id.endswith("-PLASTIC"):
            flags.append("HARD_FAIL:塑料，命中用户黑名单")
    return flags
```

Implement `_score` with weights `0.4 / 0.2 / 0.2 / 0.2`, cap reasons at three, and implement the async `@tool` function with monitor start/end calls, descending sorting, `top_n` slicing, and at most eight rejection messages.

- [x] **Step 4: Verify GREEN**

Run: `rtk test uv run pytest tests/test_item_picker.py -q`

Expected: all ItemPicker tests pass.

### Task 2: ShoppingSummary output

**Files:**
- Create: `tests/test_shopping_summary.py`
- Create: `app/tools/shopping_summary.py`

- [x] **Step 1: Write failing tests**

Use a local fake LLM because the real service is external. Assert that the tool sends one system message and one user JSON message, serializes picks using `model_dump()`, returns the LLM content as `final_text`, preserves picks, and maps `None` preferences to `[]`.

```python
result = await shopping_summary.ainvoke({
    "picks": [pick.model_dump()],
    "user_query": "找一个旅行背包",
    "new_preferences": None,
})
assert result.final_text == "最终推荐"
assert result.picks == [pick]
assert result.learned_preferences == []
```

- [x] **Step 2: Verify RED**

Run: `rtk test uv run pytest tests/test_shopping_summary.py -q`

Expected: collection fails because `app.tools.shopping_summary` does not exist.

- [x] **Step 3: Implement the tool**

Define `ShoppingSummaryOutput` and the async tool. Build messages as:

```python
messages = [
    ("system", get_shopping_summary_prompt()),
    ("user", json.dumps({
        "user_query": user_query,
        "picks": [pick.model_dump() for pick in picks],
    }, ensure_ascii=False)),
]
```

Call `await get_llm().ainvoke(messages)`, normalize `resp.content` to a string, report duration, and return the Pydantic output.

- [x] **Step 4: Verify GREEN**

Run: `rtk test uv run pytest tests/test_shopping_summary.py -q`

Expected: all ShoppingSummary tests pass.

### Task 3: Fork depth guard

**Files:**
- Create: `tests/test_fork_guard.py`
- Create: `tests/test_dispatch_tool.py`
- Create: `app/agent/fork_guard.py`
- Modify: `app/agent/dispatch_tool.py`

- [x] **Step 1: Write failing guard tests**

Assert default depth zero, nested contexts yield depths one and two, a third entry raises `ForkLimitExceeded`, exceptions restore the previous depth, and concurrent async workers retain independent depths.

```python
assert current_fork_depth() == 0
with enter_fork() as first:
    assert first == 1
    with enter_fork() as second:
        assert second == 2
        with pytest.raises(ForkLimitExceeded):
            with enter_fork():
                pass
assert current_fork_depth() == 0
```

- [x] **Step 2: Verify RED**

Run: `rtk test .venv/bin/pytest tests/test_fork_guard.py -q`

Expected: collection fails because `app.agent.fork_guard` does not exist.

- [x] **Step 3: Write failing dispatch protection tests**

With a local fake sub-agent, assert that dispatch creates an ID ending in `-d1`, passes `recursion_limit=12`, restores thread context, converts `ForkLimitExceeded` into a refusal string, and converts an async timeout into a string containing `90s 未完成`.

- [x] **Step 4: Implement the guard and integrate dispatch**

Create a `ContextVar[int]` with default zero, `MAX_FORK_DEPTH = 2`, `ForkLimitExceeded`, `enter_fork()`, and `current_fork_depth()`. In `dispatch_tool`, remove the module-level `FULL_TOOL_SET` import, define `SUB_AGENT_TIMEOUT_SEC = 90` and `SUB_AGENT_MAX_ITERATIONS = 12`, lazily import the registry inside the function, and execute:

```python
with enter_fork():
    sub_thread_id = f"sub-{uuid4().hex[:8]}-d{depth}"
    sub_agent = create_react_agent(...)
    result = await asyncio.wait_for(
        sub_agent.ainvoke(
            {"messages": [("user", demands)]},
            config={
                "configurable": {"thread_id": sub_thread_id},
                "recursion_limit": SUB_AGENT_MAX_ITERATIONS,
            },
        ),
        timeout=SUB_AGENT_TIMEOUT_SEC,
    )
```

Catch `ForkLimitExceeded` and `asyncio.TimeoutError` outside the guard and return the specified readable messages. Always reset context tokens in `finally`.

- [x] **Step 5: Verify GREEN**

Run: `rtk test .venv/bin/pytest tests/test_fork_guard.py tests/test_dispatch_tool.py -q`

Expected: all ForkGuard and DispatchTool tests pass.

### Task 4: Tool result truncation middleware

**Files:**
- Create: `tests/test_middleware.py`
- Create: `app/agent/middleware.py`

- [x] **Step 1: Write failing boundary tests**

Assert text at or below `MAX_TOOL_RESULT_TOKENS * 4` characters is unchanged. Assert longer text is truncated, contains `工具结果过长已截断`, and does not exceed the cap plus the fixed suffix length. Assert `LoopDetector` returns `False` before four matching calls in its six-call window, `True` at four, and returns to `False` after enough different tools evict old entries.

- [x] **Step 2: Verify RED**

Run: `rtk test .venv/bin/pytest tests/test_middleware.py -q`

Expected: collection fails because `app.agent.middleware` does not exist.

- [x] **Step 3: Implement minimal truncation**

```python
MAX_TOOL_RESULT_TOKENS = 4000

def truncate_long_tool_result(result_text: str) -> str:
    cap = MAX_TOOL_RESULT_TOKENS * 4
    if len(result_text) <= cap:
        return result_text
    head = result_text[: cap - 200]
    tail = "\n\n[...工具结果过长已截断，主 loop 可调更窄的查询参数]"
    return head + tail
```

Add:

```python
class LoopDetector:
    def __init__(self, window: int = 6, repeat_threshold: int = 4) -> None:
        self.window = window
        self.threshold = repeat_threshold
        self._recent: deque[str] = deque(maxlen=window)

    def record(self, tool_name: str) -> bool:
        self._recent.append(tool_name)
        return self._recent.count(tool_name) >= self.threshold
```

- [x] **Step 4: Verify GREEN**

Run: `rtk test .venv/bin/pytest tests/test_middleware.py -q`

Expected: all middleware tests pass.

### Task 5: Agent prompt guardrails

**Files:**
- Create: `tests/test_prompts.py`
- Modify: `app/prompt/prompts.yml`

- [x] **Step 1: Write a failing prompt test**

Load `get_system_prompt()` and assert it contains `立刻调用 shopping_summary`, `new_preferences`, `[dispatch_tool 拒绝]`, `[dispatch_tool 超时]`, and `重复调用 4 次`.

- [x] **Step 2: Verify RED**

Run: `rtk test .venv/bin/pytest tests/test_prompts.py -q`

Expected: assertions fail because the guardrail text is absent.

- [x] **Step 3: Append the rules**

Append the provided 收尾规则 and fork 防失控提醒 to the YAML `system_prompt` block, preserving valid indentation and the existing `{long_term_preferences}` placeholder.

- [x] **Step 4: Verify GREEN**

Run: `rtk test .venv/bin/pytest tests/test_prompts.py -q`

Expected: prompt test passes.

### Task 6: FULL_TOOL_SET registration and verification

**Files:**
- Create: `tests/test_tool_registry.py`
- Create: `app/agent/tool_registry.py`
- Modify: `app/agent/tools.py`

- [x] **Step 1: Write a failing registry test**

Parse `app/agent/tool_registry.py` and assert the registered names are exactly:

```python
{
    "item_search",
    "category_insight",
    "item_picker",
    "price_compare",
    "shipping_calc",
    "shopping_summary",
    "dispatch_tool",
}
```

- [x] **Step 2: Verify RED**

Run: `rtk test .venv/bin/pytest tests/test_tool_registry.py -q`

Expected: failure because `FULL_TOOL_SET` currently contains only `item_search`.

- [x] **Step 3: Update the registry**

In `tool_registry.py`, import the five tool modules under `app.tools`, retain `item_search` from its current `app.agent.item_search` location, and import the guarded `dispatch_tool`. Define:

```python
FULL_TOOL_SET = [
    item_search,
    category_insight,
    item_picker,
    price_compare,
    shipping_calc,
    shopping_summary,
    dispatch_tool,
]
```

Make the old module a compatibility export:

```python
from app.agent.tool_registry import FULL_TOOL_SET

__all__ = ["FULL_TOOL_SET"]
```

- [x] **Step 4: Run focused and full verification**

Run:

```bash
rtk test .venv/bin/pytest tests/test_item_picker.py tests/test_shopping_summary.py tests/test_fork_guard.py tests/test_dispatch_tool.py tests/test_middleware.py tests/test_prompts.py tests/test_tool_registry.py -q
rtk test .venv/bin/pytest -q
rtk test .venv/bin/basedpyright app/tools/item_picker.py app/tools/shopping_summary.py app/agent/fork_guard.py app/agent/dispatch_tool.py app/agent/middleware.py app/agent/tool_registry.py app/agent/tools.py
```

Expected: focused tests pass; full-suite output is recorded separately if unrelated pre-existing failures remain; basedpyright reports no errors in changed production files.

### Task 7: Workspace cleanup

**Files:**
- Inspect: repository root and test cache directories

- [x] **Step 1: Remove only task-created scratch artifacts**

Delete temporary outputs created by test runs if present, while retaining source tests, design, and plan documents. Do not remove existing user files.

- [x] **Step 2: Report final file set**

Run: `rtk tree -L 3 app/tools app/agent tests docs/superpowers`

Expected: the two new tool modules, fork guard, middleware, tool registry, seven focused test files, design document, and implementation plan are present; no scratch files remain.

> Commit steps are omitted because `/Users/Z1nk/Desktop/proj/Globex` is not a Git repository.
