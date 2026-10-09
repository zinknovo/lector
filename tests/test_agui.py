"""AG-UI 远端接口：标准事件序列、游标重放、取消与校验。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import server, task_runner
from app.api import agui as agui_module
from app.api.monitor import monitor


@pytest.fixture(autouse=True)
def _isolated_log_dir(tmp_path, monkeypatch):
    """事件日志落到临时目录，测试不污染 output/ 也不跨测试互相影响。"""
    monkeypatch.setattr(agui_module.agui_runtime, "log_dir", tmp_path / "agui")
    yield


def _sse_frames(body: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for frame in body.split("\n\n"):
        lines = [line for line in frame.split("\n") if line.strip()]
        data = "\n".join(
            line[5:].lstrip() for line in lines if line.startswith("data:")
        )
        if not data:
            continue
        event = json.loads(data)
        event_id = next(
            (line[3:].strip() for line in lines if line.startswith("id:")), None
        )
        frames.append({"id": event_id, "event": event})
    return frames


def _payload(run_id: str, thread_id: str, query: str = "美国站卖保温杯") -> dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "messages": [{"id": f"m-{run_id}", "role": "user", "content": query}],
        "tools": [],
        "context": [],
        "forwardedProps": {"userId": "user-1"},
        "state": {},
    }


def test_run_streams_standard_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(
        query: str, thread_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        await monitor.report_tool_start("item_search", {"query": query})
        await monitor.report_tool_end("item_search", 12)
        await monitor.report_event(
            "drift_signal", "目标偏移提示", {"kind": "goal_drift"}
        )
        await monitor.report_task_result("报告正文")
        return {"status": "ok"}

    monkeypatch.setattr(task_runner, "run_agent", fake_run)
    with TestClient(server.app) as client:
        response = client.post(
            "/ag-ui/run", json=_payload("run-1", "thread-1")
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-run-id"] == "run-1"
        frames = _sse_frames(response.text)

    types = [frame["event"]["type"] for frame in frames]
    assert types[0] == "RUN_STARTED"
    assert "STATE_SNAPSHOT" in types
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_ARGS" in types
    assert "TOOL_CALL_END" in types
    assert "MESSAGES_SNAPSHOT" in types
    assert types[-1] == "RUN_FINISHED"

    # 游标格式与业务扩展事件
    assert all(
        frame["id"].startswith("run-1:") for frame in frames if frame["id"]
    )
    custom_names = [
        frame["event"]["name"]
        for frame in frames
        if frame["event"]["type"] == "CUSTOM"
    ]
    assert "activity.upsert" in custom_names
    assert "drift_signal" in custom_names

    # camelCase 字段（AG-UI 线上格式）
    started = frames[0]["event"]
    assert started["threadId"] == "thread-1"
    assert started["runId"] == "run-1"
    tool_start = next(
        frame["event"] for frame in frames if frame["event"]["type"] == "TOOL_CALL_START"
    )
    assert tool_start["toolCallName"] == "item_search"

    snapshot = next(
        frame["event"]
        for frame in frames
        if frame["event"]["type"] == "MESSAGES_SNAPSHOT"
    )
    assert snapshot["messages"][-1]["content"] == "报告正文"

    finished = frames[-1]["event"]
    assert finished["outcome"] == {"type": "success"}


def test_resume_from_cursor_only_returns_later_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        query: str, thread_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        await monitor.report_task_result("完成")
        return {"status": "ok"}

    monkeypatch.setattr(task_runner, "run_agent", fake_run)
    with TestClient(server.app) as client:
        first = client.post("/ag-ui/run", json=_payload("run-2", "thread-2"))
        frames = _sse_frames(first.text)
        third_seq = frames[2]["id"].split(":")[-1]
        resumed = client.get(
            f"/ag-ui/runs/run-2/events", params={"after": int(third_seq)}
        )
        assert resumed.status_code == 200
        later = _sse_frames(resumed.text)
        assert later, "游标之后应能重放到剩余事件"
        assert all(
            int(frame["id"].split(":")[-1]) > int(third_seq) for frame in later
        )
        assert later[-1]["event"]["type"] == "RUN_FINISHED"


def test_cancel_marks_run_as_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """取消语义在 runtime 层验证（HTTP 取消路由的 404/接线另有测试覆盖）。"""
    from ag_ui.core import RunAgentInput

    from app.api.agui import AGUIRunRuntime

    async def fake_run(
        query: str, thread_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        await asyncio.Event().wait()  # 永不结束：等待被取消
        return {"status": "ok"}

    monkeypatch.setattr(task_runner, "run_agent", fake_run)

    async def scenario() -> None:
        runtime = AGUIRunRuntime(log_dir=tmp_path / "agui")
        body = RunAgentInput.model_validate(_payload("run-3", "thread-3"))
        record = await runtime.start(body, "美国站卖保温杯", "user-1")
        await asyncio.sleep(0.05)
        assert record.status == "running"

        cancelled = await runtime.cancel("run-3")
        assert cancelled.status == "cancelled"

        events, status, last = runtime.events("run-3", 0)
        types = [item["event"]["type"] for item in events]
        assert types[0] == "RUN_STARTED"
        assert types[-1] == "RUN_ERROR"
        assert events[-1]["event"]["code"] == "CANCELLED"
        assert status == "cancelled"
        assert last == events[-1]["seq"]

    asyncio.run(scenario())


def test_validation_rejects_client_tools_and_bad_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(
        query: str, thread_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        return {"status": "ok"}

    monkeypatch.setattr(task_runner, "run_agent", fake_run)
    with TestClient(server.app) as client:
        with_tools = _payload("run-4", "thread-4")
        with_tools["tools"] = [{"name": "x"}]
        assert client.post("/ag-ui/run", json=with_tools).status_code == 422

        bad_last = _payload("run-5", "thread-5")
        bad_last["messages"] = [
            {"id": "m1", "role": "assistant", "content": "你好"}
        ]
        assert client.post("/ag-ui/run", json=bad_last).status_code == 422

        empty = _payload("run-6", "thread-6")
        empty["messages"] = [{"id": "m1", "role": "user", "content": "   "}]
        assert client.post("/ag-ui/run", json=empty).status_code == 422


def test_unknown_run_returns_404() -> None:
    with TestClient(server.app) as client:
        assert client.get("/ag-ui/runs/nope").status_code == 404
        assert client.post("/ag-ui/runs/nope/cancel").status_code == 404


def test_completed_run_is_replayed_from_disk(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """进程重启后（新 runtime 实例）仍能按游标重放已完成的运行。"""

    async def fake_run(
        query: str, thread_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        await monitor.report_task_result("完成")
        return {"status": "ok"}

    monkeypatch.setattr(task_runner, "run_agent", fake_run)
    with TestClient(server.app) as client:
        first = client.post("/ag-ui/run", json=_payload("run-disk", "thread-disk"))
        assert first.status_code == 200

    restarted = agui_module.AGUIRunRuntime(
        log_dir=agui_module.agui_runtime.log_dir
    )
    events, status, last = restarted.events("run-disk", 0)
    types = [item["event"]["type"] for item in events]
    assert status == "completed"
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert last == events[-1]["seq"]


def test_unfinished_run_is_marked_interrupted(tmp_path) -> None:
    """没有终态事件的日志在重启后如实标记为 interrupted。"""
    log_dir = tmp_path / "agui"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "run-half.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "event": {
                    "type": "RUN_STARTED",
                    "threadId": "thread-half",
                    "runId": "run-half",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    runtime = agui_module.AGUIRunRuntime(log_dir=log_dir)
    events, status, _ = runtime.events("run-half", 0)
    types = [item["event"]["type"] for item in events]
    assert status == "interrupted"
    assert types[-1] == "RUN_ERROR"
    assert events[-1]["event"]["code"] == "INTERRUPTED"
    assert any(
        item["event"].get("name") == "run_interrupted" for item in events
    )


def test_duplicate_run_id_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(
        query: str, thread_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        await monitor.report_task_result("完成")
        return {"status": "ok"}

    monkeypatch.setattr(task_runner, "run_agent", fake_run)
    with TestClient(server.app) as client:
        assert client.post("/ag-ui/run", json=_payload("run-dup", "thread-dup")).status_code == 200
        again = client.post("/ag-ui/run", json=_payload("run-dup", "thread-dup"))
        assert again.status_code == 409


def test_invalid_run_or_thread_id_is_rejected() -> None:
    with TestClient(server.app) as client:
        bad_run = _payload("../evil", "thread-ok")
        assert client.post("/ag-ui/run", json=bad_run).status_code == 422
        bad_thread = _payload("run-ok", "../evil")
        assert client.post("/ag-ui/run", json=bad_thread).status_code == 422
