import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_task_registry_replacement_is_identity_safe() -> None:
    from app.api.server import TaskRegistry

    async def scenario() -> None:
        registry = TaskRegistry()
        release = asyncio.Event()

        async def wait_forever() -> None:
            await release.wait()

        first = registry.start("thread-1", wait_forever())
        second = registry.start("thread-1", wait_forever())
        await asyncio.sleep(0)

        assert first.cancelled()
        registry.discard_if_current("thread-1", first)
        assert registry.get("thread-1") is second

        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second

    asyncio.run(scenario())


def test_create_and_cancel_task(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import server

    started = asyncio.Event()

    async def fake_run_agent(
        query: str, thread_id: str, user_id: str | None = None
    ) -> dict[str, object]:
        assert query == "find a bag"
        assert thread_id == "thread-1"
        assert user_id == "user-1"
        started.set()
        await asyncio.Event().wait()
        return {"status": "ok"}

    monkeypatch.setattr(server, "run_agent", fake_run_agent)
    with TestClient(server.app) as client:
        response = client.post(
            "/api/task",
            json={
                "query": "find a bag",
                "thread_id": "thread-1",
                "user_id": "user-1",
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "started", "thread_id": "thread-1"}

        cancel = client.post("/api/task/thread-1/cancel")
        assert cancel.status_code == 200
        assert cancel.json() == {
            "status": "cancelling",
            "thread_id": "thread-1",
        }


@pytest.mark.parametrize("query", ["", "   "])
def test_create_task_rejects_blank_query(query: str) -> None:
    from app.api.server import app

    with TestClient(app) as client:
        response = client.post("/api/task", json={"query": query})

    assert response.status_code == 422


def test_cancel_missing_task_returns_404() -> None:
    from app.api.server import app

    with TestClient(app) as client:
        response = client.post("/api/task/missing/cancel")

    assert response.status_code == 404


def test_websocket_announces_session_and_handles_heartbeat() -> None:
    from app.api.server import app

    with TestClient(app) as client:
        with client.websocket_connect("/ws/thread-ws") as websocket:
            event = websocket.receive_json()
            assert event["type"] == "monitor_event"
            assert event["event"] == "session_created"
            assert event["data"] == {"thread_id": "thread-ws"}
            assert event["timestamp"].endswith("Z")

            websocket.send_text("ping")
            assert websocket.receive_text() == "pong"
