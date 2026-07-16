# FastAPI Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver the chapter 15 FastAPI backend with safe files, cancellable background tasks, and reconnectable AGUI events.

**Architecture:** FastAPI routes delegate AgentLoop execution to background asyncio tasks. The connection manager owns live sockets and bounded per-thread replay buffers; path helpers enforce filesystem boundaries.

**Tech Stack:** Python 3.11, FastAPI, asyncio, Pydantic, pytest, Starlette TestClient, basedpyright.

---

### Task 1: Path validation

**Files:**
- Modify: `app/utils/path_utils.py`
- Test: `tests/test_path_utils.py`

- [x] Write failing tests proving valid IDs pass and traversal/prefix-confusion paths fail.
- [x] Run `UV_CACHE_DIR=/tmp/globex-uv-cache uv run pytest tests/test_path_utils.py -q`; expect failures for missing validation.
- [x] Add strict thread ID and filename validation plus `Path.relative_to` boundary checks.
- [x] Re-run the focused tests; expect all pass.

### Task 2: Reconnectable connection manager

**Files:**
- Modify: `app/api/connection.py`
- Test: `tests/test_connection.py`

- [x] Write failing async tests for replay ordering, bounded buffers, connection replacement, and identity-safe disconnect.
- [x] Run the focused tests; expect failures because replay storage is absent.
- [x] Store up to 200 copied payloads per thread and replay them during connect before registering live delivery.
- [x] Re-run the focused tests; expect all pass.

### Task 3: FastAPI task and WebSocket routes

**Files:**
- Create: `app/api/server.py`
- Test: `tests/test_server.py`

- [x] Write failing TestClient tests for create, replace, cancel, WebSocket session/replay, and ping/pong.
- [x] Run the focused tests; expect import or route failures.
- [x] Implement `TaskRegistry`, request validation, task runner error reporting, and routes.
- [x] Re-run the focused tests; expect all pass.

### Task 4: Safe upload and download

**Files:**
- Modify: `app/api/server.py`
- Modify: `pyproject.toml`
- Test: `tests/test_server_files.py`

- [x] Write failing tests for accepted images, rejected type/size/path, valid download, and directory rejection.
- [x] Run focused tests; expect missing route behavior.
- [x] Add multipart dependency, chunked size-limited writes, cleanup, and safe FileResponse handling.
- [x] Re-run focused tests; expect all pass.

### Task 5: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

- [x] Document the uvicorn command and API surface; ignore runtime upload/output directories.
- [x] Run `UV_CACHE_DIR=/tmp/globex-uv-cache uv run pytest -q` and require zero failures.
- [x] Run `UV_CACHE_DIR=/tmp/globex-uv-cache uv run basedpyright app` and require zero errors.
- [x] Inspect the final diff/files and remove temporary artifacts created during verification.

## Self-review

All design requirements map to a task. Names and route paths match the chapter protocol. The plan contains no deferred implementation placeholders.
