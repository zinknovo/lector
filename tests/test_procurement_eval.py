"""采购价金标：结构自检、统计口径与门禁。"""

from types import SimpleNamespace

import pytest

from scripts.run_procurement_eval import run_gold, validate_gold


def _sample(**updates) -> dict:
    base = {
        "category": "蓝牙耳机",
        "price_min": 20,
        "price_max": 60,
        "acceptable_sources": ["web_search"],
    }
    base.update(updates)
    return base


class TestValidation:
    def test_valid_sample_passes(self) -> None:
        assert validate_gold([_sample()]) == []

    def test_inverted_range_is_rejected(self) -> None:
        problems = validate_gold([_sample(price_min=80, price_max=20)])
        assert any("不能大于" in problem for problem in problems)

    def test_unknown_source_is_rejected(self) -> None:
        problems = validate_gold([_sample(acceptable_sources=["guess"])])
        assert any("未知来源" in problem for problem in problems)

    def test_missing_category_is_rejected(self) -> None:
        problems = validate_gold([_sample(category="  ")])
        assert any("category" in problem for problem in problems)


class TestRun:
    def test_counts_hits_misses_and_sources(self) -> None:
        async def invoke(category: str):
            if category == "蓝牙耳机":
                return SimpleNamespace(procurement_cost_cny=35.0, source="web_search")
            if category == "保温杯":
                return SimpleNamespace(
                    procurement_cost_cny=12.0, source="retail_ratio_estimate"
                )
            return SimpleNamespace(procurement_cost_cny=None, source="unavailable")

        samples = [
            _sample(),
            _sample(
                category="保温杯",
                price_min=40,
                price_max=80,
                acceptable_sources=["web_search"],
            ),  # 估算来源不在可接受集合 → 未命中
            _sample(
                category="手机壳",
                price_min=5,
                price_max=20,
                acceptable_sources=["web_search"],
            ),  # 不可用 → 未命中
        ]
        report = __import__("asyncio").run(run_gold(samples, invoke=invoke))

        assert report["samples"] == 3
        assert report["hits"] == 1
        assert report["hit_rate"] == pytest.approx(1 / 3)
        assert report["source_distribution"] == {
            "web_search": 1,
            "retail_ratio_estimate": 1,
            "unavailable": 1,
        }
        assert [row["category"] for row in report["misses"]] == ["保温杯", "手机壳"]

    def test_price_outside_range_is_a_miss(self) -> None:
        async def invoke(_category: str):
            return SimpleNamespace(procurement_cost_cny=99.0, source="web_search")

        report = __import__("asyncio").run(
            run_gold([_sample()], invoke=invoke)
        )
        assert report["hit_rate"] == 0.0
