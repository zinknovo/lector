from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from app.tools.selection_decision import selection_decision


def _load_cases() -> list[dict]:
    path = Path("eval/cases/selection_decision_gates.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Invalid eval cases yaml shape")
    return cases


def test_selection_decision_evidence_gates() -> None:
    cases = _load_cases()
    for case in cases:
        inputs = case["inputs"]
        expected = case["expected"]["recommendation"]
        result = asyncio.run(selection_decision.ainvoke(inputs))
        actual = result.recommendation.value
        assert (
            actual == expected
        ), f"case={case.get('id')} expected={expected} actual={actual} risks={result.risks}"

