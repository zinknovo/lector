"""AgentLoop 任务的共享执行封装：会话目录 + 线程上下文 + 错误上报。

``/api/task``（WS 兼容路径）与 ``/ag-ui/run``（标准路径）共用同一入口，
保证两条传输的事件来源与失败语义一致。
"""

from __future__ import annotations

import asyncio

from app.agent.main import run_agent
from app.api.context import thread_scope
from app.api.monitor import monitor
from app.utils.path_utils import ensure_session_dir


async def run_agent_scoped(
    query: str, thread_id: str, user_id: str | None = None
) -> None:
    """在正确的会话作用域内执行一次 AgentLoop；错误统一转为 monitor 事件。"""
    session_dir = ensure_session_dir(thread_id)
    with thread_scope(thread_id, session_dir):
        try:
            await run_agent(query, thread_id, user_id=user_id)
        except asyncio.CancelledError:
            await monitor.report_error("cancelled", "任务被取消")
            raise
        except Exception as exc:  # noqa: BLE001 —— 边界统一上报；取消异常不吞
            await monitor.report_error("internal_error", str(exc))
