"""极简进口税率表：按销售目标市场粗估（实际应按 HS Code 查询）。"""

from typing import Literal

from app.recall.cost_tables import load_duty_tables

# destination → (rate, tier)；税率作用在申报货值上
DUTY_BY_DESTINATION_DEFAULT: dict[
    str, tuple[float, Literal["免征", "标准", "高税"]]
] = {
    "US": (0.08, "标准"),
    "UK": (0.10, "标准"),
    "DE": (0.10, "标准"),
    "JP": (0.08, "标准"),
    "CN": (0.13, "标准"),
}

# 兼容旧 platform 维度
DUTY_TABLE_DEFAULT: dict[str, tuple[float, Literal["免征", "标准", "高税"]]] = {
    "amazon": DUTY_BY_DESTINATION_DEFAULT["US"],
    "shopee": (0.06, "免征"),
    "aliexpress": DUTY_BY_DESTINATION_DEFAULT["US"],
    "ebay": (0.12, "高税"),
}

DUTY_BY_DESTINATION, DUTY_TABLE = load_duty_tables(
    DUTY_BY_DESTINATION_DEFAULT,
    DUTY_TABLE_DEFAULT,
)


def estimate_duty(
    declared_value_cny: float,
    platform: str = "amazon",
    destination: str = "US",
) -> tuple[float, Literal["免征", "标准", "高税"]]:
    """估算进口侧关税参考金额。

    declared_value_cny 应为货值（优先采购成本）；若只有售价，调用方应传入估算货值。
    """
    dest = (destination or "US").upper()
    if dest in DUTY_BY_DESTINATION:
        rate, tier = DUTY_BY_DESTINATION[dest]
    else:
        rate, tier = DUTY_TABLE.get(platform, DUTY_BY_DESTINATION["US"])
    return round(declared_value_cny * rate, 2), tier
