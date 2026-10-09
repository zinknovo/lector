"""会话导出：候选案例结构、原始查询/信号/证据采集与脱敏。"""

import json

import pytest
import yaml

from scripts.export_case import export_case


def _write_session(root, thread_id: str = "t1") -> None:
    session = root / thread_id
    log_dir = session / "agui"
    log_dir.mkdir(parents=True)
    events = [
        {
            "type": "RUN_STARTED",
            "threadId": thread_id,
            "runId": "run-x",
            "input": {
                "messages": [{"role": "user", "content": "美国站卖保温杯"}]
            },
        },
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "selection_decision"},
        {
            "type": "TOOL_CALL_ARGS",
            "toolCallId": "c1",
            "delta": json.dumps(
                {
                    "product_id": "A1",
                    "title": "保温杯",
                    "platform": "amazon",
                    "overall_score": 0.8,
                    "confidence": 0.9,
                    "recommendation": "watch",
                    "evidence": ["x"],
                },
                ensure_ascii=False,
            ),
        },
        {"type": "TOOL_CALL_END", "toolCallId": "c1"},
        {
            "type": "CUSTOM",
            "name": "drift_signal",
            "value": {"message": "目标偏移提示", "kind": "goal_drift"},
        },
        {"type": "RUN_FINISHED", "threadId": thread_id, "runId": "run-x"},
    ]
    (log_dir / "run-x.jsonl").write_text(
        "\n".join(
            json.dumps({"seq": index + 1, "event": event}, ensure_ascii=False)
            for index, event in enumerate(events)
        )
        + "\n",
        encoding="utf-8",
    )
    (session / "evidence.jsonl").write_text(
        json.dumps(
            {
                "field": "procurement_cost_cny",
                "value": 12.5,
                "method": "extracted",
                "source": "web_search",
                "detail": "key=sk-abcdefghijklmnopqrstuv123456",
                "confidence": 0.7,
                "observed_at": "2026-01-01T00:00:00Z",
                "tool": "procurement_quote",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_export_builds_candidate_case_with_redaction(tmp_path) -> None:
    _write_session(tmp_path)
    target = export_case("t1", session_root=tmp_path, out_dir=tmp_path / "out")

    raw = target.read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnopqrstuv123456" not in raw  # 脱敏
    assert "已脱敏" in raw

    payload = yaml.safe_load(raw)
    assert payload["query"] == "美国站卖保温杯"
    assert payload["source"]["thread_id"] == "t1"
    assert any(
        signal["name"] == "drift_signal" for signal in payload["signals"]
    )
    assert payload["evidence"][0]["field"] == "procurement_cost_cny"

    candidates = payload["candidate_cases"]
    assert len(candidates) == 1
    assert candidates[0]["inputs"]["product_id"] == "A1"
    # 嵌套字段（list）不进标量输入，expected 留空待人工补
    assert "evidence" not in candidates[0]["inputs"]
    assert candidates[0]["expected"] == {}
    assert "人工补" in candidates[0]["note"]


def test_export_rejects_missing_session_and_bad_thread_id(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        export_case("missing", session_root=tmp_path, out_dir=tmp_path / "out")
    with pytest.raises(ValueError):
        export_case("../evil", session_root=tmp_path, out_dir=tmp_path / "out")
