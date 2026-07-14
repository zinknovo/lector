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
