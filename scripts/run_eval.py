"""Run lightweight business-accuracy eval cases.

This runner is intentionally deterministic and does not require external data sources.
It focuses on core gating rules for selection decisions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from app.tools.selection_decision import Recommendation, selection_decision


def _load_cases(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Invalid cases yaml shape: expected {cases: [...]} ")
    return cases


async def _run_one(case: dict) -> dict:
    inputs = case.get("inputs", {})
    expected = case.get("expected", {})
    result = await selection_decision.ainvoke(inputs)

    expected_reco = expected.get("recommendation")
    actual_reco = result.recommendation.value if isinstance(result.recommendation, Recommendation) else str(result.recommendation)

    ok = expected_reco == actual_reco
    return {
        "id": case.get("id"),
        "expected": expected_reco,
        "actual": actual_reco,
        "ok": ok,
        "missing_data": result.missing_data,
        "risks": result.risks,
        "reasons": result.reasons,
        "confidence": result.confidence,
        "overall_score": result.overall_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default=str(Path("eval/cases/selection_decision_gates.yaml")),
        help="Path to cases yaml",
    )
    parser.add_argument("--output", default=None, help="Optional json output path")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    cases = _load_cases(cases_path)

    async def _run_all() -> list[dict]:
        tasks = [_run_one(case) for case in cases]
        return await asyncio.gather(*tasks)

    results = asyncio.run(_run_all())
    passed = all(r["ok"] for r in results)
    report = {
        "cases_count": len(cases),
        "passed": passed,
        "results": results,
    }

    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()

