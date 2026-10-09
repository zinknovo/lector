from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from scripts.run_eval import run_case


def _load_cases() -> list[dict]:
    path = Path("eval/cases/selection_decision_gates.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Invalid eval cases yaml shape")
    return cases


def test_selection_decision_evidence_gates() -> None:
    for case in _load_cases():
        result = asyncio.run(run_case(case))
        assert result["ok"], (
            f"case={case.get('id')} expected={result['expected']} "
            f"actual={result['actual']} missing_evidence={result['missing_evidence_fields']} "
            f"risks={result['risks']}"
        )


def test_gates_use_stored_evidence_over_model_claims() -> None:
    """模型转述的高置信度不能覆盖证据库中的估算值。"""
    cases = [
        case
        for case in _load_cases()
        if case.get("id") == "stored_low_confidence_overrides_model_claim"
    ]
    assert cases, "缺少证据库优先用例"
    result = asyncio.run(run_case(cases[0]))
    assert result["ok"], result
