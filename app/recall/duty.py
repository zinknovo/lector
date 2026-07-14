"""极简的通用税率表（实际应按 HS Code + 原产地查）。"""

from typing import Literal

DUTY_TABLE: dict[str, tuple[float, Literal["免征", "标准", "高税"]]] = {
    "amazon": (0.13, "标准"),
    "shopee": (0.06, "免征"),  # 走跨境直邮单笔免税额度
    "aliexpress": (0.13, "标准"),
    "ebay": (0.20, "高税"),  # 假设非 EPR 商家
}


def estimate_duty(price_cny: float, platform: str) -> tuple[float, Literal["免征", "标准", "高税"]]:
    """估算关税金额和税率档位。"""
    rate, tier = DUTY_TABLE.get(platform, (0.13, "标准"))
    return round(price_cny * rate, 2), tier
