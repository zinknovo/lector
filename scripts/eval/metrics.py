"""检索评测指标：Recall@K / Precision@K / MRR / NDCG@K 与门禁。

与参考实现一致的口径：

- 相关性用分级标注（0-3），二元命中阈值在数据集里显式约定；
- NDCG 收益 = 2^等级 - 1，折扣 log2(位置 + 1)；
- 聚合按查询取均值，另报空结果查询的准确率。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

# 二元命中阈值：等级 >= 2 才计入召回/排序命中
BINARY_RELEVANCE_THRESHOLD = 2


def binary_hits(
    retrieved: Sequence[str], relevant: Mapping[str, int]
) -> list[str]:
    return [
        item_id
        for item_id in retrieved
        if relevant.get(item_id, 0) >= BINARY_RELEVANCE_THRESHOLD
    ]


def recall_at_k(
    retrieved: Sequence[str], relevant: Mapping[str, int], k: int
) -> float:
    expected = [
        item_id
        for item_id, grade in relevant.items()
        if grade >= BINARY_RELEVANCE_THRESHOLD
    ]
    if not expected:
        return 1.0  # 没有期望命中时，召回不惩罚
    hits = set(binary_hits(retrieved[:k], relevant))
    return len(hits & set(expected)) / len(expected)


def precision_at_k(
    retrieved: Sequence[str], relevant: Mapping[str, int], k: int
) -> float:
    if k <= 0:
        raise ValueError("k 必须为正")
    return len(binary_hits(retrieved[:k], relevant)) / k


def reciprocal_rank(retrieved: Sequence[str], relevant: Mapping[str, int]) -> float:
    for rank, item_id in enumerate(retrieved, start=1):
        if relevant.get(item_id, 0) >= BINARY_RELEVANCE_THRESHOLD:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved: Sequence[str], relevant: Mapping[str, int], k: int
) -> float:
    def gain(grade: int) -> float:
        return float(2**grade - 1)

    dcg = 0.0
    for rank, item_id in enumerate(retrieved[:k], start=1):
        dcg += gain(relevant.get(item_id, 0)) / math.log2(rank + 1)

    ideal_grades = sorted(
        (grade for grade in relevant.values() if grade > 0), reverse=True
    )[:k]
    idcg = 0.0
    for rank, grade in enumerate(ideal_grades, start=1):
        idcg += gain(grade) / math.log2(rank + 1)

    if idcg == 0.0:
        return 1.0
    return dcg / idcg


def no_result_accuracy(
    *, retrieved: Sequence[str], expect_no_result: bool
) -> float:
    is_empty = len(retrieved) == 0
    return 1.0 if is_empty == expect_no_result else 0.0


def aggregate(results: Sequence[Mapping[str, float]]) -> dict[str, float]:
    if not results:
        return {}
    keys = results[0].keys()
    return {
        key: sum(float(result[key]) for result in results) / len(results)
        for key in keys
    }


def check_gates(
    metrics: Mapping[str, float], gates: Mapping[str, float]
) -> list[str]:
    """返回未通过的门禁说明；空列表表示全部通过。"""
    failures: list[str] = []
    for name, minimum in gates.items():
        actual = metrics.get(name)
        if actual is None:
            failures.append(f"缺少指标 {name}")
        elif actual < minimum:
            failures.append(f"{name}={actual:.3f} 低于门禁 {minimum}")
    return failures
