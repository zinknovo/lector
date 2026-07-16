# Request Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add typed request-context setters and getters for thread IDs and session directories.

**Architecture:** A focused `app.api.context` module owns two `ContextVar` instances. Public functions write and read values scoped to the current Python execution context; tests exercise defaults, updates, and task isolation.

**Tech Stack:** Python 3.11+, standard-library `contextvars`, `pathlib`, `asyncio`, pytest

---

### Task 1: Request context module

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/context.py`
- Test: `tests/test_context.py`

- [x] **Step 1: Write failing tests**

```python
import asyncio
from contextvars import Context
from pathlib import Path

from app.api.context import get_session_dir, get_thread_id, set_thread_context


def test_context_defaults_to_none() -> None:
    context = Context()
    assert context.run(get_thread_id) is None
    assert context.run(get_session_dir) is None


def test_set_thread_context_updates_both_values() -> None:
    context = Context()
    session_dir = Path("/tmp/globex-session")
    context.run(set_thread_context, "thread-123", session_dir)
    assert context.run(get_thread_id) == "thread-123"
    assert context.run(get_session_dir) == session_dir


def test_async_tasks_keep_separate_contexts() -> None:
    async def worker(thread_id: str) -> tuple[str | None, Path | None]:
        session_dir = Path("/tmp") / thread_id
        set_thread_context(thread_id, session_dir)
        await asyncio.sleep(0)
        return get_thread_id(), get_session_dir()

    async def run_workers() -> list[tuple[str | None, Path | None]]:
        return await asyncio.gather(worker("thread-a"), worker("thread-b"))

    assert asyncio.run(run_workers()) == [
        ("thread-a", Path("/tmp/thread-a")),
        ("thread-b", Path("/tmp/thread-b")),
    ]
```

- [x] **Step 2: Verify the tests fail because the module is absent**

Run: `rtk test .venv/bin/pytest tests/test_context.py`

Expected: collection error containing `ModuleNotFoundError: No module named 'app.api'`.

- [x] **Step 3: Add the minimal implementation**

Create an empty `app/api/__init__.py` and add:

```python
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

_thread_id_var: ContextVar[Optional[str]] = ContextVar(
    "globex_thread_id", default=None
)
_session_dir_var: ContextVar[Optional[Path]] = ContextVar(
    "globex_session_dir", default=None
)


def set_thread_context(thread_id: str, session_dir: Path) -> None:
    """请求入口处调用，写入本次任务的身份信息。"""
    _thread_id_var.set(thread_id)
    _session_dir_var.set(session_dir)


def get_thread_id() -> Optional[str]:
    return _thread_id_var.get()


def get_session_dir() -> Optional[Path]:
    return _session_dir_var.get()
```

- [x] **Step 4: Verify the new and existing tests pass**

Run: `rtk test .venv/bin/pytest`

Expected: `7 passed` with no warnings or errors.

No commit step is included because `/Users/Z1nk/Desktop/proj/Globex` is not a Git repository.
