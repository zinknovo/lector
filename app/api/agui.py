"""AG-UI 远端接口：标准 POST + SSE，事件由 monitor 事件投影而来。

与参考工程同一套结构（不承载业务决策）：

- ``AGUIRunAdapter``：把 monitor 业务事件投影为标准 AG-UI 事件；
- ``AGUIRunRuntime``：运行独立于 HTTP 订阅存在，事件带 seq 游标写入内存日志；
- 路由：``POST /ag-ui/run``、``GET /ag-ui/runs/{run_id}/events``、
  ``POST /ag-ui/runs/{run_id}/cancel``。

工具结果内容不进事件流（与既有 WS 协议一致）；结果事实通过最终消息、
执行记录与报告导出交付。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ag_ui.core import (
    AssistantMessage,
    BaseEvent,
    CustomEvent,
    MessagesSnapshotEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunFinishedSuccessOutcome,
    RunStartedEvent,
    StateSnapshotEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.run_events import observe_thread_events
from app.api.task_runner import run_agent_scoped

_TOOL_LABELS = {
    "planner": "拆解选品意图",
    "chat_fallback": "闲聊兜底",
    "web_search": "检索外部资料",
    "market_trend_research": "市场趋势调研",
    "product_scraper": "抓取商品数据",
    "exchange_rate": "查询汇率",
    "category_insight": "读取品类知识卡",
    "item_search": "召回候选商品",
    "item_picker": "筛选候选",
    "price_compare": "比价归一",
    "market_price_search": "搜索售价证据",
    "shipping_calc": "估算头程与关税",
    "procurement_quote": "查询采购报价",
    "profit_calculator": "计算利润",
    "supplier_evaluator": "评估供应商风险",
    "selection_decision": "汇总选品决策",
    "shopping_summary": "生成选品报告",
    "dispatch_tool": "派发子 Agent",
}


def _cancelled_error_type(error_type: object) -> bool:
    return str(error_type or "").lower() == "cancelled"


class AGUIRunAdapter:
    """把 monitor 事件投影为 AG-UI 事件；不做业务决策。"""

    def __init__(
        self, request: RunAgentInput, emit: Callable[[BaseEvent], None]
    ) -> None:
        self.request = request
        self.emit = emit
        self.state: dict[str, Any] = {
            "status": "queued",
            "progress": [],
            "activities": [],
        }
        self.error: str | None = None
        self._tool_seq = 0
        self._open_calls: dict[str, list[str]] = {}
        self._tool_open: set[str] = set()
        self._completed = False

    def _id(self, kind: str, original: str) -> str:
        return f"{self.request.run_id}:{kind}:{original}"

    def snapshot(self) -> None:
        self.emit(StateSnapshotEvent(snapshot=json.loads(json.dumps(self.state))))

    def start(self) -> None:
        self.state["status"] = "running"
        self.emit(
            RunStartedEvent(
                thread_id=self.request.thread_id, run_id=self.request.run_id
            )
        )
        self.snapshot()

    # -- 活动与进度 -------------------------------------------------------

    def _activity(self, identifier: str, *, name: str) -> dict[str, Any]:
        entries: list[dict[str, Any]] = self.state["activities"]
        entry = next((item for item in entries if item["id"] == identifier), None)
        if entry is None:
            entry = {
                "id": identifier,
                "runId": self.request.run_id,
                "kind": "tool",
                "label": _TOOL_LABELS.get(name, name or "执行工具"),
                "toolName": name,
                "toolCallId": identifier,
                "status": "running",
                "sequence": len(entries) + 1,
                "startedAt": _now_ms(),
                "finishedAt": None,
            }
            entries.append(entry)
        return entry

    def _publish_activity(self, entry: dict[str, Any]) -> None:
        self.emit(
            CustomEvent(
                name="activity.upsert",
                value=json.loads(json.dumps(entry)),
            )
        )

    def _progress(self, identifier: str, label: str, status: str) -> None:
        entries: list[dict[str, Any]] = self.state["progress"]
        entry = next((item for item in entries if item["id"] == identifier), None)
        if entry is None:
            entries.append({"id": identifier, "label": label, "status": status})
        else:
            entry.update(label=label, status=status)

    # -- monitor 事件投影 -------------------------------------------------

    def on_monitor_event(self, payload: dict[str, object]) -> None:
        event = str(payload.get("event", ""))
        raw_data = payload.get("data")
        data: dict[str, Any] = dict(raw_data) if isinstance(raw_data, dict) else {}
        message = str(payload.get("message", ""))
        if event == "tool_start":
            self._on_tool_start(data)
        elif event == "tool_end":
            self._on_tool_end(data)
        elif event == "task_result":
            final = str(data.get("final_answer", ""))
            self.finish(final)
        elif event == "error":
            self.fail(
                message or "任务执行失败",
                cancelled=_cancelled_error_type(data.get("error_type")),
                code=str(data.get("error_type") or "AGENT_ERROR"),
            )
        elif event == "fork":
            self.emit(
                CustomEvent(
                    name="fork",
                    value={
                        "subThreadId": data.get("sub_thread_id"),
                        "demands": data.get("demands"),
                    },
                )
            )
        else:
            # 业务扩展事件（证据核验、漂移提示、循环提示、注入过滤等）
            self.emit(
                CustomEvent(
                    name=event or "notice",
                    value={**data, "message": message},
                )
            )
            self.snapshot()

    def _on_tool_start(self, data: dict[str, Any]) -> None:
        name = str(data.get("tool_name", "tool"))
        self._tool_seq += 1
        call_id = self._id("tool", f"{self._tool_seq}:{name}")
        self._open_calls.setdefault(name, []).append(call_id)
        self._tool_open.add(call_id)
        self.emit(
            ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name)
        )
        args = data.get("args")
        if args:
            self.emit(
                ToolCallArgsEvent(
                    tool_call_id=call_id,
                    delta=json.dumps(args, ensure_ascii=False, default=str),
                )
            )
        entry = self._activity(call_id, name=name)
        self._publish_activity(entry)
        self._progress(call_id, _TOOL_LABELS.get(name, name), "running")
        self.snapshot()

    def _on_tool_end(self, data: dict[str, Any]) -> None:
        name = str(data.get("tool_name", "tool"))
        open_calls = self._open_calls.get(name) or []
        call_id = open_calls.pop(0) if open_calls else self._id("tool", f"?:{name}")
        self._tool_open.discard(call_id)
        self.emit(ToolCallEndEvent(tool_call_id=call_id))
        entry = self._activity(call_id, name=name)
        entry.update(
            status="completed",
            finishedAt=_now_ms(),
            durationMs=data.get("duration_ms"),
        )
        self._publish_activity(entry)
        self._progress(call_id, _TOOL_LABELS.get(name, name), "completed")
        self.snapshot()

    # -- 终态 -------------------------------------------------------------

    def _close_streams(self) -> None:
        for call_id in sorted(self._tool_open):
            self.emit(ToolCallEndEvent(tool_call_id=call_id))
        self._tool_open.clear()

    def _close_activities(self, status: str) -> None:
        for entry in self.state["activities"]:
            if entry["status"] == "running":
                entry.update(status=status, finishedAt=_now_ms())
                self._publish_activity(entry)

    def finish(self, final_text: str) -> None:
        if self._completed:
            return
        self._completed = True
        self._close_streams()
        self._close_activities("interrupted")
        self.emit(
            MessagesSnapshotEvent(
                messages=[
                    *self.request.messages,
                    AssistantMessage(
                        id=self._id("final", "answer"), content=final_text
                    ),
                ]
            )
        )
        self.state["status"] = "completed"
        self.snapshot()
        self.emit(
            RunFinishedEvent(
                thread_id=self.request.thread_id,
                run_id=self.request.run_id,
                outcome=RunFinishedSuccessOutcome(type="success"),
            )
        )

    def fail(
        self, message: str, *, cancelled: bool = False, code: str | None = None
    ) -> None:
        if self._completed:
            return
        self._completed = True
        self.error = message
        self._close_streams()
        self._close_activities("cancelled" if cancelled else "error")
        self.state["status"] = "cancelled" if cancelled else "error"
        for entry in self.state["progress"]:
            if entry["status"] == "running":
                entry["status"] = "error"
        self.snapshot()
        self.emit(
            RunErrorEvent(
                message=message, code="CANCELLED" if cancelled else (code or None)
            )
        )

    def finalize_if_open(self) -> None:
        """运行结束但未收到终态事件时，如实收口而不是留下悬挂状态。"""
        if not self._completed:
            self.fail("本轮执行未返回明确终态，请查看执行记录后重试。")


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


@dataclass
class RunRecord:
    run_id: str
    thread_id: str
    user_id: str | None
    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    adapter: AGUIRunAdapter | None = None
    seq: int = 0

    def append(self, event: BaseEvent) -> None:
        self.seq += 1
        self.events.append(
            {
                "seq": self.seq,
                "event": event.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            }
        )


class RunConflict(Exception):
    """同一 run_id 已存在。"""


class RunNotFound(Exception):
    """run_id 不存在。"""


class AGUIRunRuntime:
    """内存运行日志；运行独立于 HTTP 订阅存在。"""

    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}

    async def start(
        self, body: RunAgentInput, query: str, user_id: str | None
    ) -> RunRecord:
        if body.run_id in self.runs:
            raise RunConflict(body.run_id)
        # 同一会话的旧运行先按既有语义停掉（对齐 /api/task 的单任务行为）
        for record in list(self.runs.values()):
            if record.thread_id == body.thread_id and record.status == "running":
                await self.cancel(record.run_id)
        record = RunRecord(
            run_id=body.run_id, thread_id=body.thread_id, user_id=user_id
        )
        self.runs[body.run_id] = record
        record.task = asyncio.create_task(
            self._produce(record, body, query),
            name=f"agui-run:{body.run_id}",
        )
        return record

    async def _produce(
        self, record: RunRecord, body: RunAgentInput, query: str
    ) -> None:
        adapter = AGUIRunAdapter(body, record.append)
        record.adapter = adapter
        with observe_thread_events(record.thread_id, adapter.on_monitor_event):
            adapter.start()
            try:
                await run_agent_scoped(query, record.thread_id, record.user_id)
            except asyncio.CancelledError:
                adapter.fail("本轮执行已中断", cancelled=True)
                record.status = "cancelled"
                raise
            except Exception:  # noqa: BLE001 —— 流已开始，只能用协议错误收口
                adapter.fail("本轮服务暂时未能完成请求，请重试。")
                record.status = "error"
            else:
                adapter.finalize_if_open()
                record.status = (
                    "error"
                    if adapter.state["status"] == "error"
                    else "cancelled"
                    if adapter.state["status"] == "cancelled"
                    else "completed"
                )

    async def cancel(self, run_id: str) -> RunRecord:
        record = self.runs.get(run_id)
        if record is None:
            raise RunNotFound(run_id)
        if record.task is not None and not record.task.done():
            record.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await record.task
        if record.status == "running":
            record.status = "cancelled"
            adapter = record.adapter
            if adapter is not None:
                with contextlib.suppress(Exception):
                    adapter.fail("本轮执行已中断", cancelled=True)
        return record

    def events(
        self, run_id: str, after: int
    ) -> tuple[list[dict[str, Any]], str, int]:
        record = self.runs.get(run_id)
        if record is None:
            raise RunNotFound(run_id)
        pending = [item for item in record.events if int(item["seq"]) > after]
        return pending, record.status, record.seq

    def run(self, run_id: str) -> RunRecord:
        record = self.runs.get(run_id)
        if record is None:
            raise RunNotFound(run_id)
        return record


def _extract_query(body: RunAgentInput) -> str:
    if body.tools:
        raise HTTPException(status_code=422, detail="当前接口只执行后端工具，尚未支持前端 tools")
    if not body.thread_id.strip() or not body.run_id.strip():
        raise HTTPException(status_code=422, detail="threadId 和 runId 不能为空")
    if not body.messages or body.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="messages 最后一项必须是本轮 user 消息")
    content = body.messages[-1].content
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=422, detail="当前接口需要非空的纯文本 user 消息")
    return content.strip()


def register_ag_ui_routes(api: FastAPI, runtime: AGUIRunRuntime) -> None:
    def translate(error: Exception) -> HTTPException:
        if isinstance(error, RunNotFound):
            return HTTPException(status_code=404, detail=str(error))
        return HTTPException(status_code=409, detail=str(error))

    def cursor(request: Request, run_id: str, after: int) -> int:
        header = request.headers.get("last-event-id")
        if not header:
            return after
        prefix, separator, value = header.rpartition(":")
        if not separator or prefix != run_id or not value.isdigit():
            raise HTTPException(status_code=409, detail="Last-Event-ID 与当前运行不匹配")
        return int(value)

    async def replay(run_id: str, after: int):
        while True:
            try:
                events, status, last = runtime.events(run_id, after)
            except RunNotFound:
                return
            for item in events:
                after = int(item["seq"])
                yield f"id: {run_id}:{after}\ndata: {json.dumps(item['event'], ensure_ascii=False)}\n\n"
            if status != "running" and after >= last:
                return
            if not events:
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.15)

    def response(run_id: str, after: int) -> StreamingResponse:
        return StreamingResponse(
            replay(run_id, after),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "X-Run-Id": run_id,
            },
        )

    @api.post("/ag-ui/run")
    async def run_agent(body: RunAgentInput, request: Request) -> StreamingResponse:
        query = _extract_query(body)
        props = body.forwarded_props if isinstance(body.forwarded_props, dict) else {}
        user_id = props.get("userId")
        if user_id is not None and not isinstance(user_id, str):
            raise HTTPException(status_code=422, detail="forwardedProps.userId 必须是字符串")
        try:
            after = cursor(request, body.run_id, 0)
            await runtime.start(body, query, user_id)
        except RunConflict as error:
            raise translate(error) from error
        return response(body.run_id, after)

    @api.get("/ag-ui/runs/{run_id}/events")
    async def run_events(
        run_id: str, request: Request, after: int = Query(0, ge=0)
    ) -> StreamingResponse:
        try:
            runtime.run(run_id)
        except RunNotFound as error:
            raise translate(error) from error
        return response(run_id, cursor(request, run_id, after))

    @api.get("/ag-ui/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, object]:
        try:
            record = runtime.run(run_id)
        except RunNotFound as error:
            raise translate(error) from error
        return {
            "runId": record.run_id,
            "threadId": record.thread_id,
            "status": record.status,
            "lastSeq": record.seq,
        }

    @api.post("/ag-ui/runs/{run_id}/cancel")
    async def cancel(run_id: str) -> dict[str, object]:
        try:
            record = await runtime.cancel(run_id)
        except RunNotFound as error:
            raise translate(error) from error
        return {"runId": record.run_id, "status": record.status}


agui_runtime = AGUIRunRuntime()
