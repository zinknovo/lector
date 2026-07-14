"""汇率服务（简化为静态表）。"""

from typing import Final

# 实际项目应接实时汇率服务并加缓存
FX_RATES: Final[dict[str, float]] = {
    "CNY": 1.0,
    "USD": 7.18,
    "SGD": 5.32,
    "GBP": 9.05,
    "EUR": 7.78,
    "JPY": 0.046,
}


def to_base(amount: float, currency: str, base: str = "CNY") -> float:
    """把 amount 从 currency 换算成 base 币种。"""
    if currency not in FX_RATES or base not in FX_RATES:
        raise ValueError(f"未知币种: {currency} 或 {base}")
    return amount * FX_RATES[currency] / FX_RATES[base]
