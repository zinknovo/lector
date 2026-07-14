"""WebSocket connection manager for AGUI event delivery."""

import asyncio
from collections import defaultdict, deque
from collections.abc import Mapping

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self, buffer_size: int = 200) -> None:
        if buffer_size < 1:
            raise ValueError("buffer_size 必须大于 0")
        self.active: dict[str, WebSocket] = {}
        self._events: defaultdict[str, deque[dict[str, object]]] = defaultdict(
            lambda: deque(maxlen=buffer_size)
        )
        self._lock: asyncio.Lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, thread_id: str) -> None:
        await websocket.accept()
        async with self._lock:
            self.active[thread_id] = websocket
            for payload in self._events.get(thread_id, ()):
                await websocket.send_json(payload)

    async def disconnect(self, websocket: WebSocket, thread_id: str) -> None:
        # 关键：判断对象身份，避免重连时误刷新连接
        async with self._lock:
            if self.active.get(thread_id) is websocket:
                del self.active[thread_id]

    async def send_to_thread(self, payload: Mapping[str, object], thread_id: str) -> None:
        buffered_payload = dict(payload)
        async with self._lock:
            self._events[thread_id].append(buffered_payload)
            ws = self.active.get(thread_id)
        if ws is None:
            return
        try:
            await ws.send_json(buffered_payload)
        except Exception:
            # 发送异常一般是连接已断
            await self.disconnect(ws, thread_id)

    async def clear_events(self, thread_id: str) -> None:
        """Forget replay history when a thread starts a new logical run."""
        async with self._lock:
            self._events.pop(thread_id, None)


manager = ConnectionManager()
