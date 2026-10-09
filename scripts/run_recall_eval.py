"""品类知识召回评测：标注集 + Recall@K / MRR / NDCG@K + 门禁。

确定性、无外部依赖：用内存集合复刻 Mongo 查询语义（品类归一 + 置信度
过滤 + 排序 + 上限），真实调用 ``MongoCategoryKnowledgeStore`` 的检索路径。
失败查询可用 ``--failures-out`` 沉淀为案例文件，进入回归。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from app.recall.category_kb import CategoryCard
from app.recall.category_store import MongoCategoryKnowledgeStore
from scripts.eval.metrics import (
    aggregate,
    check_gates,
    ndcg_at_k,
    no_result_accuracy,
    recall_at_k,
    reciprocal_rank,
)

DEFAULT_CASES = Path("eval/cases/category_recall.yaml")
DEFAULT_CARDS = Path("eval/fixtures/category_cards_eval.jsonl")


def _sort_key(document: dict[str, Any], key: str) -> tuple[int, float, str]:
    """同列取值类型一致；异类型也给可比键，避免 None 参与比较。"""
    value = document.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (1, float(value), "")
    return (0, 0.0, str(value) if value is not None else "")


class InMemoryCursor:
    """支持 sort/limit 的内存游标（方向 1 升序 / -1 降序）。"""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def sort(self, spec: list[tuple[str, int]]) -> "InMemoryCursor":
        for key, direction in reversed(spec):
            self._documents.sort(
                key=lambda doc, sort_key=key: _sort_key(doc, sort_key),
                reverse=direction == -1,
            )
        return self

    def limit(self, value: int) -> "InMemoryCursor":
        self._documents = self._documents[: max(0, value)]
        return self

    def __iter__(self):
        return iter(self._documents)


class InMemoryCollection:
    """复刻评测用到的 Mongo 查询语义：相等 / $gte / $in。"""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def create_index(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def _matches(self, document: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, condition in query.items():
            value = document.get(key)
            if isinstance(condition, dict):
                if "$gte" in condition and not (
                    value is not None and value >= condition["$gte"]
                ):
                    return False
                if "$in" in condition and value not in condition["$in"]:
                    return False
            elif value != condition:
                return False
        return True

    def find(self, query: dict[str, Any]) -> InMemoryCursor:
        return InMemoryCursor(
            [
                dict(document)
                for document in self._documents
                if self._matches(document, query)
            ]
        )


def _load_cards(path: Path) -> list[CategoryCard]:
    cards: list[CategoryCard] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            cards.append(CategoryCard.model_validate(json.loads(stripped)))
    return cards


def build_store(cards: list[CategoryCard]) -> MongoCategoryKnowledgeStore:
    documents = [card.model_dump(mode="json") for card in cards]
    return MongoCategoryKnowledgeStore(collection=InMemoryCollection(documents))


async def run_queries(
    cases: dict[str, Any], store: MongoCategoryKnowledgeStore
) -> list[dict[str, Any]]:
    k = int(cases.get("k", 5))
    results: list[dict[str, Any]] = []
    for query in cases["queries"]:
        relevant = {str(key): int(value) for key, value in (query.get("relevant") or {}).items()}
        cards = await store.search(str(query["query"]), limit=k)
        retrieved = [card.card_id for card in cards]
        expect_no_result = bool(query.get("expect_no_result", False))
        row: dict[str, Any] = {
            "id": query.get("id"),
            "query": query["query"],
            "retrieved": retrieved,
            "relevant": relevant,
            "recall@k": recall_at_k(retrieved, relevant, k),
            "mrr": reciprocal_rank(retrieved, relevant),
            "ndcg@k": ndcg_at_k(retrieved, relevant, k),
            "no_result_accuracy": no_result_accuracy(
                retrieved=retrieved, expect_no_result=expect_no_result
            ),
        }
        row["ok"] = (
            row["no_result_accuracy"] == 1.0
            and (
                not relevant
                or row["recall@k"] == 1.0
            )
        )
        results.append(row)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="品类知识召回评测")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--failures-out",
        type=Path,
        default=None,
        help="把未通过的查询沉淀为案例文件（YAML，可并入标注集）",
    )
    args = parser.parse_args()

    cases = yaml.safe_load(args.cases.read_text(encoding="utf-8"))
    store = build_store(_load_cards(args.cards))
    results = asyncio.run(run_queries(cases, store))

    # 排序类指标只对有期望命中的查询取均值；空结果查询单独用准确率口径。
    ranked_rows = [row for row in results if row["relevant"]]
    metrics = aggregate(
        [
            {
                "recall@k": row["recall@k"],
                "mrr": row["mrr"],
                "ndcg@k": row["ndcg@k"],
            }
            for row in ranked_rows
        ]
    )
    metrics["no_result_accuracy"] = (
        sum(row["no_result_accuracy"] for row in results) / len(results)
        if results
        else 1.0
    )
    gate_failures = check_gates(metrics, cases.get("gates") or {})
    failed_queries = [row for row in results if not row["ok"]]

    report = {
        "queries_count": len(results),
        "metrics": metrics,
        "gate_failures": gate_failures,
        "passed": not gate_failures,
        "failed_queries": [row["id"] for row in failed_queries],
        "results": results,
    }
    if args.output:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.failures_out and failed_queries:
        failures = {
            "queries": [
                {
                    "id": row["id"],
                    "query": row["query"],
                    "retrieved": row["retrieved"],
                    "relevant": row["relevant"],
                }
                for row in failed_queries
            ]
        }
        args.failures_out.parent.mkdir(parents=True, exist_ok=True)
        args.failures_out.write_text(
            yaml.safe_dump(failures, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
