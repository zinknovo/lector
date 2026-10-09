"""检索指标：手算样例与边界。"""

import math

import pytest

from scripts.eval.metrics import (
    aggregate,
    check_gates,
    ndcg_at_k,
    no_result_accuracy,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

# 教学样例（与教程 13-2 同一组数据）：
# A、B 直接满足（3 分），C 是套装（2 分），D 超预算（0），
# Y 场景相关（1 分，不计入二元命中），X 无关（0）
RELEVANT = {"A": 3, "B": 3, "C": 2, "D": 0, "X": 0, "Y": 1}


def test_recall_uses_binary_threshold() -> None:
    # 候选 [A, B, X, Y]，K=4：命中 A、B，漏掉 C
    assert recall_at_k(["A", "B", "X", "Y"], RELEVANT, 4) == pytest.approx(2 / 3)


def test_recall_ignores_grade_one_items() -> None:
    # Y 只有 1 分，不计入有效相关集合
    assert recall_at_k(["Y"], RELEVANT, 1) == 0.0


def test_precision_uses_k_as_denominator() -> None:
    assert precision_at_k(["X", "B", "A"], RELEVANT, 3) == pytest.approx(2 / 3)


def test_mrr_returns_first_relevant_rank() -> None:
    assert reciprocal_rank(["X", "B", "A"], RELEVANT) == pytest.approx(1 / 2)
    assert reciprocal_rank(["X", "Y"], RELEVANT) == 0.0


def test_ndcg_matches_hand_computation() -> None:
    # [X, B, A]：DCG = 0 + 7/log2(3) + 7/log2(4)
    dcg = 7 / math.log2(3) + 7 / math.log2(4)
    idcg = 7 + 7 / math.log2(3) + 3 / math.log2(4)
    assert ndcg_at_k(["X", "B", "A"], RELEVANT, 3) == pytest.approx(dcg / idcg)

    # [A, B, X]：命中不变但位置更好
    better = 7 + 7 / math.log2(3)
    assert ndcg_at_k(["A", "B", "X"], RELEVANT, 3) == pytest.approx(better / idcg)

    # [A, B, C]：到达理想顺序
    assert ndcg_at_k(["A", "B", "C"], RELEVANT, 3) == pytest.approx(1.0)


def test_no_result_accuracy() -> None:
    assert no_result_accuracy(retrieved=[], expect_no_result=True) == 1.0
    assert no_result_accuracy(retrieved=["A"], expect_no_result=True) == 0.0
    assert no_result_accuracy(retrieved=["A"], expect_no_result=False) == 1.0


def test_aggregate_averages_each_metric() -> None:
    metrics = aggregate([{"recall": 1.0, "mrr": 0.5}, {"recall": 0.0, "mrr": 1.0}])
    assert metrics == {"recall": 0.5, "mrr": 0.75}


def test_check_gates_reports_failures() -> None:
    failures = check_gates({"recall": 0.8, "mrr": 0.9}, {"recall": 0.9, "mrr": 0.8})
    assert len(failures) == 1
    assert "recall" in failures[0]
