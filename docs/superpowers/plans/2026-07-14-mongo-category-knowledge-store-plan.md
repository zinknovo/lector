# Mongo Category Knowledge Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Tower/OpenSearch category-knowledge path with an asynchronous MongoDB-backed store while preserving the `category_insight` tool contract.

**Architecture:** `category_insight` depends on a small `CategoryKnowledgeStore` protocol. `MongoCategoryKnowledgeStore` wraps existing synchronous PyMongo calls with `asyncio.to_thread`, uses normalized exact-category lookup, and lazily creates its client and indexes. The existing builder becomes a Mongo JSONL importer; all Tower/OpenSearch runtime paths are removed.

**Tech Stack:** Python 3.11+, Pydantic, PyMongo, LangChain async tools, pytest, Docker Compose, uv.

## Global Constraints

- Do not modify `app/agent/main_agent.py`, `server.py`, or `middleware.py`.
- Keep `category_insight`'s public tool name, arguments, output model, and monitor events compatible.
- Use `MONGODB_URL`; default database is `lector`, default collection is `category_cards`.
- Normalize categories with `normalize_category()` and require `confidence >= 0.5`.
- Sort by confidence descending, last-updated descending, then card ID ascending.
- Do not add an embedding provider, vector search, fuzzy fallback, or a new Mongo driver.
- Keep `faiss-cpu`; remove only `opensearch-py`.
- Do not modify or commit the user's `.idea` files.
- Run focused tests after every red/green cycle and the full verification suite before completion.

---

### Task 1: Add the Mongo category knowledge store

**Files:**
- Create: `app/recall/category_store.py`
- Create: `tests/test_category_store.py`

**Interfaces:**
- Consumes: `CategoryCard`, `normalize_category()`, `MONGODB_URL`.
- Produces: `CategoryKnowledgeStore.search()`, `CategoryKnowledgeStore.upsert_many()`, `MongoCategoryKnowledgeStore`, `get_category_knowledge_store()`.

- [ ] **Step 1: Write failing store tests**

Create a fake collection/cursor in `tests/test_category_store.py` and assert the exact Mongo filter, sort order, limit, category normalization, model conversion, index definitions, and normalized upserts:

```python
def test_search_normalizes_filters_sorts_and_limits() -> None:
    collection = FakeCollection([CARD_DOCUMENT])
    store = MongoCategoryKnowledgeStore(collection=collection)

    cards = asyncio.run(
        store.search("Wireless Earbuds", card_types={"bestseller"}, limit=3)
    )

    assert collection.last_filter == {
        "category": "wireless earbuds",
        "card_type": {"$in": ["bestseller"]},
        "confidence": {"$gte": 0.5},
    }
    assert collection.last_sort == [
        ("confidence", -1),
        ("last_updated", -1),
        ("card_id", 1),
    ]
    assert collection.last_limit == 3
    assert cards == [CategoryCard.model_validate(CARD_DOCUMENT)]


def test_upsert_many_creates_indexes_and_normalizes_documents() -> None:
    collection = FakeCollection([])
    store = MongoCategoryKnowledgeStore(collection=collection)

    written = asyncio.run(store.upsert_many([CARD.model_copy(update={"category": "耳机"})]))

    assert written == 1
    assert collection.indexes == [
        (("card_id", 1), {"unique": True, "name": "category_card_id_unique"}),
        (
            (("category", 1), ("card_type", 1), ("confidence", -1)),
            {"name": "category_lookup"},
        ),
    ]
    assert collection.replacements[0][1]["category"] == "wireless earbuds"
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `uv run pytest tests/test_category_store.py -q`

Expected: collection fails with `ModuleNotFoundError: app.recall.category_store`.

- [ ] **Step 3: Implement the protocol and Mongo store**

Create `app/recall/category_store.py` with these concrete signatures and behaviors:

```python
CategoryCardType = Literal["bestseller", "attribute", "price_range"]


class CategoryKnowledgeStore(Protocol):
    async def search(
        self,
        category: str,
        *,
        card_types: set[CategoryCardType] | None = None,
        limit: int = 8,
    ) -> list[CategoryCard]: ...

    async def upsert_many(self, cards: list[CategoryCard]) -> int: ...


class MongoCategoryKnowledgeStore:
    def __init__(
        self,
        *,
        collection: Any | None = None,
        mongodb_url: str | None = None,
        collection_name: str = "category_cards",
    ) -> None: ...

    async def search(...) -> list[CategoryCard]:
        if limit <= 0:
            return []
        return await asyncio.to_thread(self._search_sync, ...)

    async def upsert_many(self, cards: list[CategoryCard]) -> int:
        if not cards:
            return 0
        return await asyncio.to_thread(self._upsert_many_sync, cards)
```

Implementation requirements:

- Lazily construct `MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017/lector"))` only when no collection was injected.
- Select `client.get_default_database(default="lector")[collection_name]`.
- Guard one-time index creation with `threading.Lock` and `_indexes_ready`.
- Use `collection.find(query).sort(sort_spec).limit(limit)` for reads.
- Strip Mongo `_id` before `CategoryCard.model_validate()`.
- Use `ReplaceOne({"card_id": card.card_id}, document, upsert=True)` and `bulk_write(..., ordered=False)`.
- Return `len(cards)` after a successful bulk write so idempotent re-imports have deterministic counters.
- Sort `card_types` before placing them in `$in` for deterministic tests.
- Expose an `@lru_cache(maxsize=1)` factory named `get_category_knowledge_store()`.

- [ ] **Step 4: Run store tests**

Run: `uv run pytest tests/test_category_store.py -q`

Expected: all tests pass.

- [ ] **Step 5: Run the full Python suite and commit**

Run: `uv run pytest -q`

Expected: existing tests pass.

Commit only Task 1 files:

```bash
git add app/recall/category_store.py tests/test_category_store.py
git commit -m "feat: add Mongo category knowledge store"
```

### Task 2: Move `category_insight` onto the store interface

**Files:**
- Modify: `app/tools/category_insight.py`
- Create: `tests/test_category_insight.py`

**Interfaces:**
- Consumes: `CategoryKnowledgeStore.search()` and `get_category_knowledge_store()` from Task 1.
- Produces: `_recall_cards(category, top_k, store=None)` with no Tower/OpenSearch imports.

- [ ] **Step 1: Write failing tool tests**

Add an async fake store and cover recall, depth filtering, empty results, and error reporting:

```python
class FakeStore:
    def __init__(self, cards: list[CategoryCard], error: Exception | None = None):
        self.cards = cards
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, category: str, *, card_types=None, limit: int = 8):
        self.calls.append((category, limit))
        if self.error:
            raise self.error
        return self.cards


def test_category_insight_uses_store_and_preserves_output(monkeypatch) -> None:
    store = FakeStore(CARDS)
    monkeypatch.setattr(module, "get_category_knowledge_store", lambda: store)

    result = asyncio.run(
        module.category_insight.ainvoke({"category": "耳机", "depth": "deep"})
    )

    assert store.calls == [("wireless earbuds", 15)]
    assert result.category == "wireless earbuds"
    assert result.bestsellers[0].name == "Model A"
    assert result.attributes[0].distribution == {"塑料": 0.6, "金属": 0.4}
    assert result.confidence == 0.8


def test_category_insight_reports_and_reraises_store_error(monkeypatch) -> None:
    store = FakeStore([], RuntimeError("mongo unavailable"))
    monkeypatch.setattr(module, "get_category_knowledge_store", lambda: store)
    monkeypatch.setattr(module.monitor, "report_error", AsyncMock())

    with pytest.raises(RuntimeError, match="mongo unavailable"):
        asyncio.run(module.category_insight.ainvoke({"category": "耳机"}))

    module.monitor.report_error.assert_awaited_once()
```

- [ ] **Step 2: Run tests and verify old imports prevent isolation**

Run: `uv run pytest tests/test_category_insight.py -q`

Expected: fail because `category_insight` still imports and constructs OpenSearch/Tower resources.

- [ ] **Step 3: Replace hybrid recall with store lookup**

In `app/tools/category_insight.py`:

- Remove `os`, `Any`, `OpenSearch`, `opensearch_config`, `tower_client`, index constants, and global client.
- Import `CategoryKnowledgeStore` and `get_category_knowledge_store`.
- Implement:

```python
async def _recall_cards(
    category: str,
    top_k: int,
    store: CategoryKnowledgeStore | None = None,
) -> list[CategoryCard]:
    backend = store or get_category_knowledge_store()
    return await backend.search(category, limit=top_k)
```

- Wrap recall and output aggregation in `try/except Exception as exc`; on failure call `await monitor.report_error(type(exc).__name__, f"category_insight failed: {exc}")` and re-raise.
- Preserve existing `report_tool_start`, successful `report_tool_end`, parsers, depth limits, confidence calculation, signature, and output model.

- [ ] **Step 4: Run focused and full tests**

Run: `uv run pytest tests/test_category_insight.py tests/test_tool_registry.py tests/test_item_picker.py -q`

Expected: all pass.

Run: `uv run pytest -q`

Expected: all current tests pass except tests intentionally tied to the old builder/config, which Task 3 and Task 4 replace.

- [ ] **Step 5: Commit the tool migration**

```bash
git add app/tools/category_insight.py tests/test_category_insight.py
git commit -m "refactor: read category insights from Mongo store"
```

### Task 3: Convert the category KB builder to a Mongo importer

**Files:**
- Modify: `scripts/build_category_kb.py`
- Rewrite: `tests/test_category_kb_builder.py`
- Modify: `tests/test_cli_entrypoints.py`
- Delete: `scripts/setup_pipeline.py`
- Delete: `scripts/setup_pipeline.sh`

**Interfaces:**
- Consumes: `CategoryKnowledgeStore.upsert_many()` and `MongoCategoryKnowledgeStore`.
- Produces: `BuildCategoryKbResult(read, written, rejected)` and `build_category_kb(cards_path, store)`.

- [ ] **Step 1: Rewrite builder tests first**

Replace OpenSearch and embedding fakes with a store fake:

```python
class FakeStore:
    def __init__(self) -> None:
        self.cards: list[CategoryCard] = []

    async def upsert_many(self, cards: list[CategoryCard]) -> int:
        self.cards.extend(cards)
        return len(cards)


def test_builder_validates_normalizes_and_upserts_cards(tmp_path: Path) -> None:
    cards_path = write_cards(tmp_path, [VALID_ALIAS_CARD, LOW_CONFIDENCE_CARD])
    store = FakeStore()

    result = asyncio.run(build_category_kb(cards_path, store))

    assert result.model_dump() == {"read": 2, "written": 1, "rejected": 1}
    assert store.cards[0].category == "wireless earbuds"


def test_builder_batches_all_accepted_cards_into_one_upsert(tmp_path: Path) -> None:
    store = FakeStore()
    result = asyncio.run(build_category_kb(write_cards(tmp_path, VALID_CARDS), store))
    assert result.written == len(VALID_CARDS)
    assert len(store.cards) == len(VALID_CARDS)
```

Update `tests/test_cli_entrypoints.py` to remove `scripts/setup_pipeline.py` and retain `scripts/build_category_kb.py`.

- [ ] **Step 2: Run builder tests and verify they fail against the old API**

Run: `uv run pytest tests/test_category_kb_builder.py tests/test_cli_entrypoints.py -q`

Expected: failures reference the old `client`/`encode` signature or OpenSearch constants.

- [ ] **Step 3: Implement the importer**

Rewrite `scripts/build_category_kb.py` so it:

```python
class BuildCategoryKbResult(BaseModel):
    read: int = 0
    written: int = 0
    rejected: int = 0


async def build_category_kb(
    cards_path: Path,
    store: CategoryKnowledgeStore,
) -> BuildCategoryKbResult:
    accepted_cards: list[CategoryCard] = []
    # Read nonblank JSONL lines, count malformed/non-dict/admission failures,
    # normalize accepted card.category, and append the validated card.
    result.written = await store.upsert_many(accepted_cards)
    return result
```

`main()` must instantiate `MongoCategoryKnowledgeStore()`, keep `--cards-path`, run the async builder, and print JSON. Remove all OpenSearch, vector dimension, embedding and index mapping code.

- [ ] **Step 4: Delete obsolete pipeline setup and run tests**

Delete `scripts/setup_pipeline.py` and `scripts/setup_pipeline.sh`.

Run: `uv run pytest tests/test_category_kb_builder.py tests/test_cli_entrypoints.py -q`

Expected: all pass.

Run: `uv run pytest -q`

Expected: all remaining tests pass except the explicitly obsolete OpenSearch/readiness tests removed in Task 4.

- [ ] **Step 5: Commit the importer**

```bash
git add scripts/build_category_kb.py scripts/setup_pipeline.py scripts/setup_pipeline.sh tests/test_category_kb_builder.py tests/test_cli_entrypoints.py
git commit -m "refactor: import category cards into MongoDB"
```

### Task 4: Remove Tower/OpenSearch runtime and deployment paths

**Files:**
- Modify: `app/integrations/readiness.py`
- Modify: `scripts/smoke_external_services.py`
- Modify: `tests/test_readiness.py`
- Delete: `tests/test_opensearch_config.py`
- Delete: `app/recall/opensearch_config.py`
- Delete: `app/recall/towers.py`
- Delete: `services/tower/app.py`
- Delete: `services/tower/Dockerfile`
- Delete: `services/tower/requirements.txt`
- Delete: `services/tower/tests/test_tower.py`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: the Mongo-only category path from Tasks 1-3.
- Produces: readiness set `{apify, mongodb, llm, web_search}` and four-service Compose stack.

- [ ] **Step 1: Change configuration/readiness tests first**

In `tests/test_readiness.py`, delete Tower imports and vector/Tower tests, then add:

```python
def test_production_checks_exclude_removed_services() -> None:
    from app.integrations.readiness import _production_checks

    assert set(_production_checks()) == {"apify", "mongodb", "llm", "web_search"}
```

Create or extend a Compose/config test to load `compose.yaml` with `yaml.safe_load()` and assert:

```python
assert set(config["services"]) == {"mongodb", "agent", "gateway", "frontend"}
assert set(config.get("volumes", {})) == {"mongodb-data"}
assert set(config["services"]["agent"]["depends_on"]) == {"mongodb"}
```

- [ ] **Step 2: Run tests and verify removed services are still present**

Run: `uv run pytest tests/test_readiness.py tests/test_compose_config.py -q`

Expected: assertions fail because OpenSearch/Tower are still configured.

- [ ] **Step 3: Remove Python runtime paths and service files**

- Delete `_validate_vector`, `_check_opensearch`, `_check_tower` and their unused imports from readiness.
- Change `ALL_SERVICES` in `scripts/smoke_external_services.py` to `{"apify", "mongodb", "llm", "web_search"}` and remove OpenSearch password redaction.
- Delete `app/recall/opensearch_config.py`, `app/recall/towers.py`, `tests/test_opensearch_config.py`, and the entire `services/tower` tree.
- Run `rtk proxy rg -n 'opensearch|tower|TOWER_|OPENSEARCH_' app scripts tests services pyproject.toml` and remove every runtime reference; prompt prose describing abstract retrieval is allowed only when it does not name a removed service.

- [ ] **Step 4: Simplify Compose and dependencies**

In `compose.yaml`:

- Delete `opensearch` and `tower` services.
- Delete their Agent environment variables and `depends_on` entries.
- Delete `opensearch-data` and `huggingface-cache` volumes.

In `.env.example`, delete `TOWER_*`, `OPENSEARCH_*`, `CATEGORY_KB_INDEX`, and `CATEGORY_KB_SEARCH_PIPELINE` entries.

Remove `opensearch-py` from `pyproject.toml`, then regenerate the lock file:

Run: `uv lock`

Expected: exit 0 and OpenSearch transport dependencies are removed when no longer needed.

- [ ] **Step 5: Run focused and full tests, then commit**

Run: `uv run pytest tests/test_readiness.py tests/test_compose_config.py tests/test_cli_entrypoints.py -q`

Expected: all pass.

Run: `uv run pytest -q`

Expected: all Python tests pass.

Run: `uv run basedpyright`

Expected: 0 errors.

Commit all Task 4 paths, including deletions and `uv.lock`:

```bash
git add app/integrations/readiness.py app/recall/opensearch_config.py app/recall/towers.py scripts/smoke_external_services.py services/tower tests .env.example compose.yaml pyproject.toml uv.lock
git commit -m "chore: remove Tower and OpenSearch runtime"
```

### Task 5: Update docs/demo and verify the complete migration

**Files:**
- Modify: `README.md`
- Modify: `docs/production-readiness.md`
- Modify: `scripts/demo_selection_pipeline.py`
- Modify: other tracked docs found by the stale-reference scan only when they describe the active runtime.

**Interfaces:**
- Consumes: final Mongo store/importer and simplified Compose stack.
- Produces: accurate setup instructions and verified runnable demo/deployment configuration.

- [ ] **Step 1: Add a documentation/reference regression check**

Run the stale-reference scan before edits:

```bash
rtk proxy rg -n 'OpenSearch|Tower|OPENSEARCH_|TOWER_|setup_pipeline' README.md docs scripts compose.yaml .env.example
```

Expected: active-runtime references are reported in README, production docs, and demo/config files.

- [ ] **Step 2: Update user-facing instructions**

- Describe `category_cards` as MongoDB-backed structured knowledge.
- Document `uv run python scripts/build_category_kb.py --cards-path data/category_cards.jsonl`.
- List the default four services: MongoDB, Agent, Gateway, Frontend.
- Remove Tower/OpenSearch startup, health-check, port, model-cache, index and pipeline instructions.
- Remove Tower environment setup from `scripts/demo_selection_pipeline.py`.
- Preserve historical design/plan documents; they are records, not active runtime documentation.

- [ ] **Step 3: Verify no stale active-runtime references remain**

Run:

```bash
rtk proxy rg -n 'OpenSearch|Tower|OPENSEARCH_|TOWER_|setup_pipeline' README.md docs/production-readiness.md scripts compose.yaml .env.example app services pyproject.toml
```

Expected: no matches.

- [ ] **Step 4: Run complete verification**

Run each command separately and require exit code 0:

```bash
uv run pytest -q
uv run basedpyright
uv run python scripts/demo_selection_pipeline.py
docker compose config --services
docker compose up -d --build
docker compose ps
```

Expected:

- Python suite has 0 failures.
- BasedPyright has 0 errors.
- Demo exits successfully and prints a selection result.
- `docker compose config --services` prints exactly `mongodb`, `agent`, `gateway`, `frontend`.
- All four services reach running/healthy state as applicable.

Run any existing frontend, Java Gateway, and Tower-independent service suites documented in the repository, because Compose files and shared docs changed:

```bash
(cd frontend && npm test -- --run && npm run build)
(cd lector-api && ./mvnw test)
```

Expected: both commands exit 0.

- [ ] **Step 5: Inspect final diff and commit**

Run:

```bash
rtk git status --short
rtk diff --check
rtk diff HEAD~4..HEAD
```

Confirm only planned files are changed and `.idea` is absent from all feature commits.

Commit documentation/demo changes:

```bash
git add README.md docs/production-readiness.md scripts/demo_selection_pipeline.py
git commit -m "docs: document Mongo category knowledge workflow"
```

Do not claim completion until the full verification commands have been rerun after the final edit and their fresh output has been inspected.
