"""Run lightweight business-accuracy eval cases.

This runner is intentionally deterministic and does not require external data
sources. It focuses on core gating rules for selection decisions, plus
evidence-chain behavior: cases may seed a temporary evidence store
(``evidence:``) to verify that gates use stored provenance instead of
model-transcribed numbers, and may assert which evidence fields the decision
must carry (``expected.evidence_fields``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from app.api.context import thread_scope
from app.evidence.models import EvidenceItem, EvidenceMethod
from app.evidence.store import EvidenceStore
from app.tools.selection_decision import Recommendation, selection_decision


def _load_cases(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Invalid cases yaml shape: expected {cases: [...]} ")
    return cases


def _seed_evidence(items: list[dict], store: EvidenceStore) -> None:
    for raw in items:
        store.add(
            EvidenceItem(
                field=raw["field"],
                value=raw.get("value"),
                method=EvidenceMethod(raw.get("method", "measured")),
                source=raw.get("source", "eval"),
                detail=raw.get("detail", ""),
                confidence=raw.get("confidence"),
                observed_at=raw.get("observed_at", "2026-01-01T00:00:00Z"),
                tool=raw.get("tool", "eval"),
                product_id=raw.get("product_id"),
            )
        )


async def _invoke(case: dict):
    inputs = case.get("inputs", {})
    evidence_seed = case.get("evidence") or []
    if not evidence_seed:
        return await selection_decision.ainvoke(inputs)
    with tempfile.TemporaryDirectory() as tmp:
        session_dir = Path(tmp)
        store = EvidenceStore(session_dir / "evidence.jsonl")
        _seed_evidence(evidence_seed, store)
        with thread_scope(f"eval-{case.get('id', 'case')}", session_dir):
            return await selection_decision.ainvoke(inputs)


async def run_case(case: dict) -> dict:
    """Run one case and return a structured result (also used by tests)."""
    expected = case.get("expected", {})
    result = await _invoke(case)

    expected_reco = expected.get("recommendation")
    actual_reco = (
        result.recommendation.value
        if isinstance(result.recommendation, Recommendation)
        else str(result.recommendation)
    )
    reco_ok = expected_reco == actual_reco

    expected_fields = expected.get("evidence_fields") or []
    present_fields = [item.field for item in result.evidence]
    missing_fields = [
        field for field in expected_fields if field not in present_fields
    ]

    return {
        "id": case.get("id"),
        "expected": expected_reco,
        "actual": actual_reco,
        "ok": reco_ok and not missing_fields,
        "evidence_fields": present_fields,
        "missing_evidence_fields": missing_fields,
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
    parser.add_argument(
        "--failures-out",
        default=None,
        help="把未通过的用例沉淀为候选案例文件（YAML，可用 merge_cases.py 合并）",
    )
    args = parser.parse_args()

    cases_path = Path(args.cases)
    cases = _load_cases(cases_path)

    async def _run_all() -> list[dict]:
        tasks = [run_case(case) for case in cases]
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

    if args.failures_out:
        failing = [case for case, result in zip(cases, results) if not result["ok"]]
        if failing:
            import yaml

            path = Path(args.failures_out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.safe_dump(
                    {
                        "cases": [
                            {
                                "id": case.get("id"),
                                "inputs": case.get("inputs", {}),
                                "expected": case.get("expected", {}),
                            }
                            for case in failing
                        ]
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
