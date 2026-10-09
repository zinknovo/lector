"""会话 checkpoint：把主 AgentLoop 的状态持久化到会话目录（sqlite）。

重启后同一 thread 再次运行会接着已有状态继续（追问沿用上一次的对话与证据）。
sqlite 打开失败（权限/损坏）时降级为"无 checkpoint"并记事件，不阻断任务。
"""

from __future__ import annotations

from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import AsyncIterator

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.api.monitor import monitor

CHECKPOINT_FILENAME = "checkpoints.sqlite"


@asynccontextmanager
async def open_checkpointer(
    session_dir: Path,
) -> AsyncIterator[BaseCheckpointSaver | None]:
    """打开会话 checkpointer；不可用时产出 None（调用方按无 checkpoint 继续）。"""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    saver_cm = None
    try:
        saver_cm = AsyncSqliteSaver.from_conn_string(
            str(session_dir / CHECKPOINT_FILENAME)
        )
        saver = await saver_cm.__aenter__()
    except Exception as exc:  # noqa: BLE001 —— 任何打开失败都降级
        await monitor.report_event(
            "checkpoint_unavailable",
            f"会话 checkpoint 不可用，本次按无恢复继续：{type(exc).__name__}",
            {},
        )
        yield None
        return

    try:
        yield saver
    finally:
        with suppress(Exception):
            await saver_cm.__aexit__(None, None, None)
