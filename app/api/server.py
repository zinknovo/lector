"""FastAPI entrypoint for background AgentLoop tasks and AGUI events."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from app.agent.main import run_agent
from app.api.connection import manager
from app.api.context import thread_scope
from app.api.monitor import monitor, utc_timestamp
from app.utils import path_utils
from app.utils.path_utils import (
    ensure_session_dir,
    safe_join,
    validate_filename,
    validate_thread_id,
)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
ALLOWED_UPLOAD_TYPES: dict[str, set[str]] = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
    "image/gif": {".gif"},
}


class TaskRegistry:
    """Own the in-process task for each thread identifier."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def start(
        self, thread_id: str, coroutine: Coroutine[Any, Any, Any]
    ) -> asyncio.Task[Any]:
        old = self._tasks.get(thread_id)
        if old is not None and not old.done():
            old.cancel()
        task = asyncio.create_task(coroutine)
        self._tasks[thread_id] = task
        return task

    def get(self, thread_id: str) -> asyncio.Task[Any] | None:
        return self._tasks.get(thread_id)

    def discard_if_current(
        self, thread_id: str, task: asyncio.Task[Any]
    ) -> None:
        if self._tasks.get(thread_id) is task:
            self._tasks.pop(thread_id, None)

    def cancel(self, thread_id: str) -> bool:
        task = self._tasks.get(thread_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def cancel_all(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


task_registry = TaskRegistry()
# Chapter-facing alias retained for diagnostics and teaching examples.
active_tasks = task_registry._tasks


class TaskRequest(BaseModel):
    query: str
    thread_id: str | None = None
    user_id: str | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query 不能为空")
        return value

    @field_validator("thread_id")
    @classmethod
    def validate_optional_thread_id(cls, value: str | None) -> str | None:
        if value is not None:
            validate_thread_id(value)
        return value


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await task_registry.cancel_all()


app = FastAPI(title="Globex Agent API", lifespan=lifespan)


async def _run_task(req: TaskRequest, thread_id: str) -> None:
    current = asyncio.current_task()
    if current is None:  # pragma: no cover - asyncio always supplies one here
        raise RuntimeError("任务未运行在 asyncio Task 中")
    session_dir = ensure_session_dir(thread_id)
    with thread_scope(thread_id, session_dir):
        try:
            await run_agent(req.query, thread_id, user_id=req.user_id)
        except asyncio.CancelledError:
            await monitor.report_error("cancelled", "任务被取消")
            raise
        except Exception as exc:
            await monitor.report_error("internal_error", str(exc))
        finally:
            task_registry.discard_if_current(thread_id, current)


@app.post("/api/task")
async def create_task(req: TaskRequest) -> dict[str, str]:
    thread_id = req.thread_id or uuid.uuid4().hex
    await manager.clear_events(thread_id)
    task_registry.start(thread_id, _run_task(req, thread_id))
    return {"status": "started", "thread_id": thread_id}


@app.post("/api/task/{thread_id}/cancel")
async def cancel_task(thread_id: str) -> dict[str, str]:
    try:
        validate_thread_id(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not task_registry.cancel(thread_id):
        raise HTTPException(
            status_code=404, detail=f"任务 {thread_id} 不存在或已结束"
        )
    return {"status": "cancelling", "thread_id": thread_id}


@app.get("/api/files/{thread_id}/{filename}")
async def download_file(thread_id: str, filename: str) -> FileResponse:
    try:
        validate_thread_id(thread_id)
        validate_filename(filename)
        session_dir = path_utils.OUTPUT_ROOT / thread_id
        target = safe_join(session_dir, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{filename}")
    return FileResponse(target, filename=filename)


@app.post("/api/upload")
async def upload_file(
    thread_id: str, file: UploadFile = File(...)
) -> dict[str, str]:
    try:
        validate_thread_id(thread_id)
        filename = validate_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    suffix = Path(filename).suffix.lower()
    allowed_suffixes = ALLOWED_UPLOAD_TYPES.get(file.content_type or "")
    if allowed_suffixes is None or suffix not in allowed_suffixes:
        raise HTTPException(status_code=415, detail="仅支持 PNG、JPEG、WebP 和 GIF 图片")

    upload_dir = path_utils.ensure_upload_dir(thread_id)
    target = safe_join(upload_dir, filename)
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB 限制",
                    )
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    relative_path = Path("uploaded") / thread_id / filename
    return {"status": "ok", "path": relative_path.as_posix()}


@app.websocket("/ws/{thread_id}")
async def ws_endpoint(websocket: WebSocket, thread_id: str) -> None:
    try:
        validate_thread_id(thread_id)
    except ValueError:
        await websocket.close(code=1008, reason="thread_id 不合法")
        return

    await manager.connect(websocket, thread_id)
    try:
        await websocket.send_json(
            {
                "type": "monitor_event",
                "event": "session_created",
                "message": "会话已创建",
                "data": {"thread_id": thread_id},
                "timestamp": utc_timestamp(),
            }
        )
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, thread_id)
