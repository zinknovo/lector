"""把一次真实会话导出为 Bad-case 候选案例（教程 18 最小版）。

输入 = 会话目录（`output/<thread_id>/`）：

- `agui/*.jsonl`：运行事件日志（RUN_STARTED.input 含原始查询；
  TOOL_CALL_ARGS 含各工具调用的入参；CUSTOM 含漂移/循环/过滤等信号）；
- `evidence.jsonl`：证据库。

输出 = `eval/failures/case-<thread>-<时间戳>.yaml`：与 `eval/cases` 同构的候选
（`expected` 留空待人工填写），且全部文本过一遍脱敏。**不直接改正式用例集。**
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from app.security.guards import audit_output
from app.utils.jsonl import iter_jsonl
from app.utils.path_utils import OUTPUT_ROOT, validate_thread_id

SIGNAL_EVENTS = {
    "drift_signal",
    "loop_detected",
    "injection_filtered",
    "tool_result_capped",
    "report_number_check",
    "output_audit",
    "preference_not_saved",
    "task_incomplete",
    "tool_circuit_opened",
    "task_budget_hint",
}


def _redact(text: str) -> str:
    _, cleaned = audit_output(text)
    return cleaned


def _iter_run_events(session_dir: Path) -> list[dict[str, Any]]:
    log_dir = session_dir / "agui"
    if not log_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        for item in iter_jsonl(path):
            if isinstance(item, dict) and isinstance(item.get("event"), dict):
                events.append(item["event"])
    return events


def _extract_query(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("type") != "RUN_STARTED":
            continue
        payload = event.get("input")
        messages = payload.get("messages") if isinstance(payload, dict) else None
        if not isinstance(messages, list):
            continue
        for message in reversed(messages):
            if (
                isinstance(message, dict)
                and message.get("role") == "user"
                and isinstance(message.get("content"), str)
            ):
                return str(message["content"])
    return None


def _collect_tool_inputs(
    events: list[dict[str, Any]], tool_name: str
) -> list[dict[str, Any]]:
    """按参数流还原指定工具的入参（TOOL_CALL_START + ARGS 增量合并）。"""
    names: dict[str, str] = {}
    buffers: dict[str, str] = {}
    collected: list[dict[str, Any]] = []
    for event in events:
        kind = event.get("type")
        if kind == "TOOL_CALL_START":
            call_id = str(event.get("toolCallId", ""))
            names[call_id] = str(event.get("toolCallName", ""))
            buffers[call_id] = ""
        elif kind == "TOOL_CALL_ARGS":
            call_id = str(event.get("toolCallId", ""))
            if call_id in buffers:
                buffers[call_id] += str(event.get("delta", ""))
        elif kind == "TOOL_CALL_END":
            call_id = str(event.get("toolCallId", ""))
            if names.get(call_id) != tool_name:
                continue
            raw = buffers.pop(call_id, "")
            try:
                arguments = json.loads(raw) if raw else {}
            except ValueError:
                arguments = {"_raw": raw[:500]}
            if isinstance(arguments, dict):
                collected.append(arguments)
    return collected


def _collect_signals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "CUSTOM":
            continue
        name = str(event.get("name", ""))
        if name not in SIGNAL_EVENTS:
            continue
        value = event.get("value")
        signals.append({"name": name, "value": value})
    return signals


def _collect_evidence(session_dir: Path) -> list[dict[str, Any]]:
    path = session_dir / "evidence.jsonl"
    if not path.exists():
        return []
    return [
        item for item in iter_jsonl(path) if isinstance(item, dict)
    ]


def export_case(
    thread_id: str, *, session_root: Path = OUTPUT_ROOT, out_dir: Path | None = None
) -> Path:
    """导出一次会话为候选案例文件，返回写入路径。"""
    validated = validate_thread_id(thread_id)
    session_dir = session_root / validated
    if not session_dir.exists():
        raise FileNotFoundError(f"会话目录不存在：{session_dir}")

    events = _iter_run_events(session_dir)
    query = _extract_query(events)
    signals = _collect_signals(events)
    evidence = _collect_evidence(session_dir)
    candidate_cases = [
        {
            "id": f"from-{validated}-{index + 1}",
            "inputs": {
                key: value
                for key, value in arguments.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            },
            "expected": {},
            "note": "人工补 expected.recommendation 后，再并入 eval/cases",
            "source": {"thread_id": validated},
        }
        for index, arguments in enumerate(_collect_tool_inputs(events, "selection_decision"))
    ]

    exported_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "source": {"thread_id": validated, "exported_at": exported_at},
        "query": _redact(query) if query else None,
        "signals": json.loads(_redact(json.dumps(signals, ensure_ascii=False))),
        "evidence": json.loads(_redact(json.dumps(evidence, ensure_ascii=False))),
        "candidate_cases": candidate_cases,
    }

    target_dir = out_dir or (ROOT / "eval" / "failures")
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = exported_at.replace(":", "").replace("-", "")[:15]
    target = target_dir / f"case-{validated}-{stamp}.yaml"
    target.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="导出一次会话为 Bad-case 候选案例")
    parser.add_argument("thread_id", help="会话 thread_id")
    parser.add_argument(
        "--session-root", type=Path, default=OUTPUT_ROOT, help="会话目录根（默认 output/）"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None, help="输出目录（默认 eval/failures/）"
    )
    args = parser.parse_args()

    target = export_case(
        args.thread_id, session_root=args.session_root, out_dir=args.out_dir
    )
    print(json.dumps({"exported": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
