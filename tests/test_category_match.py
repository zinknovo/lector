"""品类一致性规则：标注表覆盖正例、负例与"无法判定"的保守分支。"""

import pytest

from app.recall.category_match import match_category

POSITIVE_CASES = [
    ("蓝牙耳机", "TOZO NC9 Hybrid ANC Wireless Earbuds"),  # 别名 → wireless earbuds
    ("wireless earbuds", "Wireless Earbuds for Running 80Hr"),
    ("旅行背包", "Travel Laptop Backpack 35L"),
    ("U型枕", "记忆棉U型枕 护颈旅行"),
    ("颈枕", "旅行枕 飞机枕 便携"),
    ("马克杯", "陶瓷马克杯 350ml 办公"),
    ("保温杯", "316不锈钢保温杯 商务直饮"),
    ("保温杯", "保温壶 大容量 户外"),
    ("无线耳机", "无线蓝牙耳机 降噪入耳"),
]

NEGATIVE_CASES = [
    ("保温杯", "紫砂茶杯 景德镇手工"),
    ("颈枕", "遮光眼罩 睡眠"),
    ("旅行背包", "Hiking Tent 2 Person Camping"),
    ("蓝牙耳机", "Bluetooth Headphones Over Ear Studio"),
    ("手机壳", "钢化玻璃保护膜"),
]

# 分属不同文字体系：规则无法判定，保守保留
UNDECIDABLE_CASES = [
    ("保温杯", "Stainless Steel Tumbler 500ml"),
    ("露营灯", "Portable Camping Lantern USB"),
]


@pytest.mark.parametrize("target,text", POSITIVE_CASES)
def test_consistent_candidates_are_kept(target: str, text: str) -> None:
    verdict = match_category(target, text)
    assert verdict.ok, f"{target} vs {text}: {verdict}"


@pytest.mark.parametrize("target,text", NEGATIVE_CASES)
def test_mismatched_candidates_are_excluded(target: str, text: str) -> None:
    verdict = match_category(target, text)
    assert not verdict.ok, f"{target} vs {text}: {verdict}"
    assert "品类不一致" in verdict.reason


@pytest.mark.parametrize("target,text", UNDECIDABLE_CASES)
def test_cross_script_pairs_are_kept_as_undecidable(target: str, text: str) -> None:
    verdict = match_category(target, text)
    assert verdict.ok
    assert "无法判定" in verdict.reason


def test_empty_inputs_skip_filtering() -> None:
    assert match_category("", "任意标题").ok
    assert match_category("保温杯", "   ").ok
