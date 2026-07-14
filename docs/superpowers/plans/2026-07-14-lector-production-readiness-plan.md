# Lector Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Turn the completed Python selection-tool MVP into a locally deployable, externally verifiable system with strict smoke checks, real category embeddings, downloadable PDF/XLSX reports, and a Spring Boot gateway.

**Architecture:** Docker Compose supplies MongoDB, OpenSearch and a BGE-M3 Query Tower. Python remains the internal Agent service and exposes generated files; a Java WebFlux gateway owns the public REST/WebSocket surface, API-key authentication, request throttling and proxying. A single smoke runner checks configured external capabilities without silently falling back to Mock.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, PyMongo, OpenSearch, sentence-transformers with BAAI/bge-m3 (1024 dimensions), Docker Compose, Spring Boot 4.1, Java 17+, Maven, Apache POI, ReportLab.

## Global Constraints

- Never commit or print API keys; `.env` stays ignored and `.env.example` contains empty values only.
- Smoke checks must return `pass`, `fail`, or `skipped` per capability and exit non-zero when a requested configured capability fails.
- Apify checks must instantiate `ApifyAmazonDataSource` directly and may not fall back to Mock.
- Query Tower output must contain exactly 1024 finite floats.
- Do not modify `app/agent/main_agent.py`, `app/api/server.py`, or `app/agent/middleware.py`.
- New Python behavior follows TDD and must pass `uv run basedpyright app tests scripts services`.
- Java gateway tests use mocked upstream HTTP/WebSocket endpoints and require no external service.

---

### Task 1: Strict external-service smoke runner

**Files:**
- Create: `app/integrations/readiness.py`
- Create: `app/integrations/__init__.py`
- Create: `scripts/smoke_external_services.py`
- Test: `tests/test_readiness.py`

**Interfaces:**
- Produces: `CheckResult(name, status, detail, duration_ms)` and `ReadinessReport(checks)`.
- Produces: `run_readiness(selected: set[str]) -> ReadinessReport`.
- CLI: `uv run python scripts/smoke_external_services.py --services apify,mongodb,llm,web_search,opensearch,tower`.

- [x] **Step 1: Write failing tests**

Test that missing credentials are `skipped`, a direct Apify adapter returns normalized Amazon products, Mongo performs ping plus cache round-trip, tower rejects vectors whose length is not 1024, and JSON output contains no secret values.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_readiness.py -v`

Expected: import failure for `app.integrations.readiness`.

- [x] **Step 3: Implement checks and CLI**

Use injected async callables for unit tests. Production adapters call `ApifyAmazonDataSource`, `MongoClient.admin.command("ping")`, `planner`, `web_search`, OpenSearch cluster health, and `TowerClient.encode_query`. Catch each capability independently and redact exception text through a helper that replaces configured secret values with `***`.

- [x] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_readiness.py -v`

Expected: all tests pass.

---

### Task 2: Local MongoDB, OpenSearch and BGE-M3 stack

**Files:**
- Create: `compose.yaml`
- Create: `services/tower/app.py`
- Create: `services/tower/requirements.txt`
- Create: `services/tower/Dockerfile`
- Create: `services/tower/tests/test_app.py`
- Modify: `.env.example`
- Modify: `scripts/setup_pipeline.py`

**Interfaces:**
- `POST /encode/query` with `{"query": "..."}` -> `{"embedding": [1024 floats]}`.
- `POST /encode/user` with `{"user_id": "..."}` -> deterministic embedding of the supplied user identifier.
- `GET /health` -> model name, dimension and readiness.
- Compose services expose MongoDB `27017`, OpenSearch `9200`, Query Tower `8001` and Python Agent `8000`.

- [x] **Step 1: Write failing tower API tests**

Inject a fake encoder and assert normalization, 1024 dimensions, empty-input rejection and health output.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest services/tower/tests/test_app.py -v`

Expected: missing `services.tower.app`.

- [x] **Step 3: Implement tower and Compose stack**

Load `SentenceTransformer("BAAI/bge-m3")` once during application lifespan, normalize embeddings, and validate dimension. Pin OpenSearch to `3.6.0`; disable the security plugin only for local development. Add healthchecks and service dependencies.

- [x] **Step 4: Validate configuration**

Run: `docker compose config --quiet` and `uv run pytest services/tower/tests/test_app.py -v`.

Expected: exit 0.

---

### Task 3: PDF and XLSX selection-report export

**Files:**
- Create: `app/reports/exporter.py`
- Create: `app/reports/__init__.py`
- Create: `scripts/export_selection_report.py`
- Test: `tests/test_report_exporter.py`
- Modify: `pyproject.toml`

**Interfaces:**
- `export_selection_report(report: ShoppingSummaryOutput, output_dir: Path, basename: str) -> ExportedReport`.
- Produces `<basename>.pdf` and `<basename>.xlsx`; `ExportedReport` contains absolute paths.

- [x] **Step 1: Write failing tests**

Build a `ShoppingSummaryOutput` with recommend/watch rows. Assert both files exist, XLSX headers and numeric cells are preserved, and PDF begins with `%PDF` and contains at least one page.

- [x] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/test_report_exporter.py -v`

Expected: missing exporter module.

- [x] **Step 3: Implement deterministic exports**

Use `openpyxl` for XLSX and ReportLab with a bundled CJK-capable CID font for PDF. Escape formulas in user-controlled spreadsheet strings by prefixing a single quote when the first character is `=`, `+`, `-`, or `@`.

- [x] **Step 4: Verify GREEN and inspect files**

Run: `uv run pytest tests/test_report_exporter.py -v`.

Expected: all tests pass with no temporary files outside pytest directories.

---

### Task 4: Spring Boot public gateway

**Files:**
- Create: `lector-api/pom.xml`
- Create: `lector-api/src/main/java/com/lector/api/LectorApiApplication.java`
- Create: `lector-api/src/main/java/com/lector/api/config/AgentProperties.java`
- Create: `lector-api/src/main/java/com/lector/api/config/SecurityConfig.java`
- Create: `lector-api/src/main/java/com/lector/api/gateway/AgentGatewayController.java`
- Create: `lector-api/src/main/java/com/lector/api/gateway/AgentGatewayService.java`
- Create: `lector-api/src/main/java/com/lector/api/security/ApiKeyWebFilter.java`
- Create: `lector-api/src/main/java/com/lector/api/security/RateLimitWebFilter.java`
- Create: `lector-api/src/main/resources/application.yml`
- Create: `lector-api/src/test/java/com/lector/api/gateway/AgentGatewayControllerTest.java`

**Interfaces:**
- Public `POST /api/task`, `POST /api/task/{threadId}/cancel`, `GET /api/files/{threadId}/{filename}` proxy to the internal Python service.
- Public `GET /actuator/health`, `/actuator/prometheus` expose operational state.
- Header `X-API-Key` is required except for health; token-bucket limit is configurable per key.
- WebSocket `/ws/{threadId}` proxies bidirectionally to Python and preserves JSON event payloads.

- [x] **Step 1: Write failing WebFlux tests**

Assert missing/incorrect keys return 401, rate-limit exhaustion returns 429, valid task requests preserve body and response, unsafe file names are rejected, and health is public.

- [x] **Step 2: Run tests and verify RED**

Run: `mvn -f lector-api/pom.xml test`

Expected: compile failure because gateway classes are absent.

- [x] **Step 3: Implement gateway and production protection**

Use Spring WebFlux `WebClient`, Spring Security, Actuator, Micrometer Prometheus and Bucket4j. Bind upstream URL, API key and rate parameters from environment variables. Do not log request authorization headers or upstream credentials.

- [x] **Step 4: Verify GREEN**

Run: `mvn -f lector-api/pom.xml test`.

Expected: all tests pass.

---

### Task 5: End-to-end documentation and verification

**Files:**
- Modify: `README.md`
- Create: `docs/production-readiness.md`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Local start: `docker compose up --build`.
- Strict smoke: `uv run python scripts/smoke_external_services.py --services configured`.
- Gateway start: `mvn -f lector-api/pom.xml spring-boot:run`.

- [x] **Step 1: Document exact startup and gate semantics**

Document which checks are locally verifiable, which require real credentials, and that a skipped Apify check is not a successful live integration.

- [x] **Step 2: Run the complete verification matrix**

Run:

```bash
uv run pytest
uv run basedpyright app tests scripts services
pnpm --dir frontend test -- --run
pnpm --dir frontend build
mvn -f lector-api/pom.xml test
docker compose config --quiet
uv run python scripts/demo_selection_pipeline.py
```

Expected: every command exits 0. Run the strict smoke runner separately; missing credentials may produce `skipped`, but configured checks must pass.

## Self-Review

- Spec coverage: strict external checks, local dependencies, real 1024-dimensional embeddings, report files, Java gateway, auth, rate limiting, metrics and documentation each have a task.
- Placeholder scan: no task permits fake production data or silent Mock fallback.
- Type consistency: Query Tower returns the 1024-vector consumed by `TowerClient`; report exporter consumes the existing `ShoppingSummaryOutput`; Java routes match the existing Python FastAPI routes.
