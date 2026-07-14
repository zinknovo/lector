import asyncio
from typing import Any

from app.api.connection import ConnectionManager


class FakeWebSocket:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.accepted = False
        self.fail_send = fail_send
        self.sent: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: Any) -> None:
        if self.fail_send:
            raise RuntimeError("closed")
        self.sent.append(dict(payload))


def test_offline_events_are_replayed_in_order_on_connect() -> None:
    async def scenario() -> None:
        manager = ConnectionManager(buffer_size=3)
        await manager.send_to_thread({"event": "one"}, "thread-1")
        await manager.send_to_thread({"event": "two"}, "thread-1")
        websocket = FakeWebSocket()

        await manager.connect(websocket, "thread-1")  # type: ignore[arg-type]

        assert websocket.accepted is True
        assert websocket.sent == [{"event": "one"}, {"event": "two"}]

    asyncio.run(scenario())


def test_event_buffer_is_bounded() -> None:
    async def scenario() -> None:
        manager = ConnectionManager(buffer_size=2)
        for number in range(3):
            await manager.send_to_thread({"number": number}, "thread-1")
        websocket = FakeWebSocket()

        await manager.connect(websocket, "thread-1")  # type: ignore[arg-type]

        assert websocket.sent == [{"number": 1}, {"number": 2}]

    asyncio.run(scenario())


def test_disconnect_of_replaced_socket_keeps_new_connection() -> None:
    async def scenario() -> None:
        manager = ConnectionManager()
        old = FakeWebSocket()
        new = FakeWebSocket()
        await manager.connect(old, "thread-1")  # type: ignore[arg-type]
        await manager.connect(new, "thread-1")  # type: ignore[arg-type]

        await manager.disconnect(old, "thread-1")  # type: ignore[arg-type]

        assert manager.active["thread-1"] is new

    asyncio.run(scenario())


def test_send_failure_removes_only_failed_connection() -> None:
    async def scenario() -> None:
        manager = ConnectionManager()
        failed = FakeWebSocket(fail_send=True)
        await manager.connect(failed, "thread-1")  # type: ignore[arg-type]

        await manager.send_to_thread({"event": "one"}, "thread-1")

        assert "thread-1" not in manager.active
        replay = FakeWebSocket()
        await manager.connect(replay, "thread-1")  # type: ignore[arg-type]
        assert replay.sent == [{"event": "one"}]

    asyncio.run(scenario())


def test_payload_is_copied_before_buffering() -> None:
    async def scenario() -> None:
        manager = ConnectionManager()
        payload: dict[str, object] = {"event": "original"}
        await manager.send_to_thread(payload, "thread-1")
        payload["event"] = "mutated"
        websocket = FakeWebSocket()

        await manager.connect(websocket, "thread-1")  # type: ignore[arg-type]

        assert websocket.sent == [{"event": "original"}]

    asyncio.run(scenario())
