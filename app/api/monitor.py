"""统一封装 AGUI 事件上报。"""

from datetime import UTC, datetime

from app.api.connection import manager
from app.api.context import get_thread_id


def utc_timestamp() -> str:
    """Return an RFC 3339 UTC timestamp matching the AGUI wire format."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Monitor:
    """统一封装 AGUI 事件上报。"""

    async def _emit(self, event: str, message: str, data: dict[str, object]) -> None:
        thread_id = get_thread_id()
        if thread_id is None:
            return  # 没有上下文（如离线脚本调用工具）就静默丢弃

        payload = {
            "type": "monitor_event",
            "event": event,
            "message": message,
            "data": data,
            "timestamp": utc_timestamp(),
        }
        await manager.send_to_thread(payload, thread_id)

    async def report_tool_start(self, tool_name: str, args: dict[str, object]) -> None:
        await self._emit("tool_start", f"正在调用 {tool_name}", {
            "tool_name": tool_name,
            "args": args,
        })

    async def report_tool_end(self, tool_name: str, duration_ms: int) -> None:
        await self._emit("tool_end", f"{tool_name} 完成", {
            "tool_name": tool_name,
            "duration_ms": duration_ms,
        })

    async def report_fork(self, sub_thread_id: str, demands: str) -> None:
        await self._emit("fork", "派发子 AgentLoop", {
            "sub_thread_id": sub_thread_id,
            "demands": demands[:200],
        })

    async def report_task_result(self, final_answer: str) -> None:
        await self._emit("task_result", "任务完成", {
            "final_answer": final_answer,
        })

    async def report_error(self, error_type: str, message: str) -> None:
        await self._emit("error", message, {"error_type": error_type})


monitor = Monitor()
