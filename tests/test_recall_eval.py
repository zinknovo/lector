"""品类召回评测：门禁、别名归一与低置信度过滤。"""

import asyncio
import json
from pathlib import Path

import yaml

from scripts.eval.metrics import check_gates
from scripts.run_recall_eval import _load_cards, build_store, run_queries

CASES_PATH = Path("eval/cases/category_recall.yaml")
CARDS_PATH = Path("eval/fixtures/category_cards_eval.jsonl")


def _run() -> dict:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    store = build_store(_load_cards(CARDS_PATH))
    results = asyncio.run(run_queries(cases, store))
    ranked = [row for row in results if row["relevant"]]
    metrics = {
        name: sum(row[name] for row in ranked) / len(ranked)
        for name in ("recall@k", "mrr", "ndcg@k")
    }
    metrics["no_result_accuracy"] = sum(
        row["no_result_accuracy"] for row in results
    ) / len(results)
    return {"results": results, "metrics": metrics}


def test_recall_eval_passes_gates() -> None:
    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    report = _run()
    failures = check_gates(report["metrics"], cases["gates"])
    assert not failures, f"{failures} | {json.dumps(report['metrics'], ensure_ascii=False)}"
    assert all(row["ok"] for row in report["results"]), report["results"]


def test_low_confidence_cards_are_filtered() -> None:
    report = _run()
    earbuds = next(row for row in report["results"] if row["id"] == "q-earbuds-zh")
    assert "earbuds-lowconf" not in earbuds["retrieved"]


def test_unknown_category_returns_no_result() -> None:
    report = _run()
    empty = next(row for row in report["results"] if row["id"] == "q-empty")
    assert empty["retrieved"] == []
    assert empty["no_result_accuracy"] == 1.0


def test_aliases_normalize_to_standard_categories() -> None:
    from app.recall.category_norm import normalize_category

    assert normalize_category("蓝牙耳机") == "wireless earbuds"
    assert normalize_category("U型枕") == "颈枕"
    assert normalize_category("马克杯") == "咖啡杯"
    assert normalize_category(" 水杯 ") == "保温杯"
