import asyncio
from pathlib import Path

from app.api import monitor as monitor_module
from app.api.context import thread_scope


def test_monitor_emits_utc_timestamp(monkeypatch) -> None:
    captured: list[tuple[dict[str, object], str]] = []

    async def fake_send(payload, thread_id: str) -> None:
        captured.append((dict(payload), thread_id))

    monkeypatch.setattr(monitor_module.manager, "send_to_thread", fake_send)

    async def scenario() -> None:
        with thread_scope("thread-1", Path("/tmp/thread-1")):
            await monitor_module.monitor.report_error("test", "failed")

    asyncio.run(scenario())

    payload, thread_id = captured[0]
    assert thread_id == "thread-1"
    assert isinstance(payload["timestamp"], str)
    assert payload["timestamp"].endswith("Z")
