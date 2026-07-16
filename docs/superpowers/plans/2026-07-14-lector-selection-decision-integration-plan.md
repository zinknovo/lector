# Lector Selection Decision Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Integrate the existing ReAct tools through a unified, deterministic `SelectionDecision` model and make Lector produce complete selection reports without inventing missing metrics.

**Architecture:** Keep the existing flexible ReAct loop. Add one pure aggregation tool that consumes existing tool outputs, computes weighted scores and confidence, and emits a stable decision object; make `shopping_summary` consume only those decisions. Update prompts and the demo to enforce the three-stage protocol.

**Tech Stack:** Python 3.11+, LangChain tools, LangGraph ReAct, Pydantic v2, pytest, YAML prompts.

## Global Constraints

- Do not modify `app/agent/main_agent.py`, `app/api/server.py`, or middleware/framework code.
- Business scores are deterministic; the LLM must not create numeric metrics.
- Missing inputs lower confidence and are listed in `missing_data`.
- Use test-first RED-GREEN cycles and run the full backend suite after every task.
- Preserve the free-form ReAct orchestration selected by the user.

---

### Task 1: Add the unified selection decision tool

**Files:**
- Create: `app/tools/selection_decision.py`
- Create: `tests/test_selection_decision.py`

**Interfaces:**
- Consumes: product identity plus optional market, profit, logistics and supplier fields.
- Produces: `SelectionDecision` with component scores, `overall_score`, `confidence`, recommendation, reasons, risks and missing fields.

- [x] **Step 1: Write failing score tests**

Test a complete strong SKU, missing profit/supplier data, and a high-risk supplier. Assert strong complete data recommends, missing dimensions cannot recommend, and high risk always rejects.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_selection_decision.py -v`

Expected: collection failure because `app.tools.selection_decision` does not exist.

- [x] **Step 3: Implement models and pure scoring helpers**

Create `Recommendation(str, Enum)`, `SelectionDecision(BaseModel)`, clamp/average helpers and four component scorers. Normalize available component weights using 0.30/0.35/0.20/0.15. Require both profit and supplier dimensions before `recommend`; force `reject` for `RiskLevel.HIGH`.

- [x] **Step 4: Implement async tool**

Expose `selection_decision(...) -> SelectionDecision` with optional fields and monitor start/end calls. Populate `missing_data` by dimension and generate deterministic reasons/risks.

- [x] **Step 5: Verify GREEN and regression safety**

Run: `uv run pytest tests/test_selection_decision.py -v`

Run: `uv run pytest`

- [x] **Step 6: Commit**

```bash
git add app/tools/selection_decision.py tests/test_selection_decision.py
git commit -m "feat: add unified selection decisions"
```

### Task 2: Make shopping summary report decisions

**Files:**
- Modify: `app/tools/shopping_summary.py`
- Modify: `tests/test_shopping_summary.py`

**Interfaces:**
- Consumes: `decisions: list[SelectionDecision]`, `user_query`, optional preferences.
- Produces: `ShoppingSummaryOutput` containing `final_text`, original decisions, report rows and learned preferences.

- [x] **Step 1: Replace the current PickedItem test with a failing decision test**

Build one `SelectionDecision`, invoke the tool with a fake LLM and assert the JSON payload preserves profit, supplier risk, confidence and missing data. Assert the report mirrors those fields.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_shopping_summary.py -v`

Expected: validation failure because the tool still requires `picks`.

- [x] **Step 3: Update report models and implementation**

Replace `picks` with `decisions`. Expand `SelectionReport` to contain recommendation, financial metrics, supplier risk, overall score, confidence, reasons, risks and missing data. Serialize only decision objects to the LLM.

- [x] **Step 4: Verify GREEN and regression safety**

Run: `uv run pytest tests/test_shopping_summary.py -v`

Run: `uv run pytest`

- [x] **Step 5: Commit**

```bash
git add app/tools/shopping_summary.py tests/test_shopping_summary.py
git commit -m "feat: report unified selection decisions"
```

### Task 3: Teach the ReAct agent the three-stage protocol

**Files:**
- Modify: `app/prompt/prompts.yml`
- Modify: `tests/test_prompts.py`

**Interfaces:**
- Produces: Lector system/planner/report prompts that describe discover, filter and full_chain paths and prohibit invented metrics.

- [x] **Step 1: Add failing prompt assertions**

Assert the system prompt contains `Lector`, all three intents, `profit_calculator`, `supplier_evaluator`, `selection_decision`, and the rule that full-chain work must aggregate decisions before summary. Assert the report prompt forbids invented numeric fields.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_prompts.py -v`

Expected: assertions fail because prompts still identify as Globex.

- [x] **Step 3: Rewrite prompt content**

Preserve ReAct/fork safety and preference injection. Replace consumer-shopping language with selection goals and define exact tool paths. State that sub-agents cannot call `shopping_summary` and missing data must remain explicit.

- [x] **Step 4: Verify GREEN and regression safety**

Run: `uv run pytest tests/test_prompts.py -v`

Run: `uv run pytest`

- [x] **Step 5: Commit**

```bash
git add app/prompt/prompts.yml tests/test_prompts.py
git commit -m "feat: align agent prompts with Lector selection"
```

### Task 4: Register the aggregation tool and update compatibility tests

**Files:**
- Modify: `app/agent/tool_registry.py`
- Modify: `tests/test_tool_registry.py`

**Interfaces:**
- Produces: `FULL_TOOL_SET` containing `selection_decision` before terminal `shopping_summary`.

- [x] **Step 1: Add a failing registry expectation**

Add `selection_decision` to the exact expected tool-name set.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_tool_registry.py -v`

- [x] **Step 3: Register the tool**

Import `selection_decision` and place it after supplier evaluation and before shopping summary.

- [x] **Step 4: Verify GREEN and regression safety**

Run: `uv run pytest tests/test_tool_registry.py -v`

Run: `uv run pytest`

- [x] **Step 5: Commit**

```bash
git add app/agent/tool_registry.py tests/test_tool_registry.py
git commit -m "feat: register selection decision tool"
```

### Task 5: Upgrade the three-stage demo and public documentation

**Files:**
- Modify: `scripts/demo_selection_pipeline.py`
- Modify: `README.md`

**Interfaces:**
- Demo produces complete `SelectionDecision` objects and passes them to `shopping_summary`.

- [x] **Step 1: Update the demo**

For each pick, compute profit and supplier risk, call `selection_decision`, print recommendation/score/confidence, then call summary with decisions. Use Mock-compatible seller data and CNY identity conversion.

- [x] **Step 2: Update README**

Rename the project to Lector, document the three stages, data sources, environment variables and demo command.

- [x] **Step 3: Run final verification**

Run: `uv run pytest`

Run: `pnpm --dir frontend test -- --run`

Run: `uv run python scripts/demo_selection_pipeline.py`

Expected: all tests pass and the demo prints at least one complete decision and report.

- [x] **Step 4: Commit and push**

```bash
git add scripts/demo_selection_pipeline.py README.md docs/superpowers/specs/2026-07-14-lector-selection-decision-integration-design.md docs/superpowers/plans/2026-07-14-lector-selection-decision-integration-plan.md
git commit -m "docs: document integrated selection workflow"
git push origin main
```

## Self-Review

- Spec coverage: unified model, deterministic weights, ReAct protocol, error handling, reporting, registration and demo are each assigned to a task.
- Placeholder scan: no implementation placeholders are present.
- Type consistency: `SelectionDecision` is created in Task 1 and consumed unchanged by Tasks 2 and 5.
