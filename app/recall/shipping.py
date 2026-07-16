"""按目的地 + 重量分档的卖家头程运费表（中国发往目标市场，CNY/件）。"""

# destination ISO → [(min_weight_kg, fee_cny, eta_days), ...]
# 默认按海运/经济头程粗估，不是消费者国际快递。
OUTBOUND_SHIPPING_TABLE: dict[str, list[tuple[float, float, int]]] = {
    "US": [(0, 18, 25), (0.5, 28, 22), (2.0, 55, 20)],
    "UK": [(0, 20, 28), (0.5, 32, 25), (2.0, 60, 22)],
    "DE": [(0, 20, 28), (0.5, 32, 25), (2.0, 60, 22)],
    "JP": [(0, 15, 12), (0.5, 24, 10), (2.0, 45, 9)],
    # 保留 CN 仅作兼容；选品主路径不应默认发往中国
    "CN": [(0, 85, 12), (0.5, 130, 10), (2.0, 240, 8)],
}

# 兼容旧调用：platform 名映射到目的地时不再使用；保留常量避免外部 import 断裂
SHIPPING_TABLE = {
    "amazon": OUTBOUND_SHIPPING_TABLE["US"],
    "shopee": OUTBOUND_SHIPPING_TABLE["US"],
    "aliexpress": OUTBOUND_SHIPPING_TABLE["US"],
    "ebay": OUTBOUND_SHIPPING_TABLE["US"],
}


def estimate_shipping(
    weight_kg: float,
    platform: str = "amazon",
    destination: str = "US",
) -> tuple[float, int]:
    """估算中国货源发往目标市场的头程运费与时效。"""
    dest = (destination or "US").upper()
    table = OUTBOUND_SHIPPING_TABLE.get(dest) or OUTBOUND_SHIPPING_TABLE["US"]
    # platform 参数保留兼容，目的地优先
    del platform
    fee, eta = table[0][1], table[0][2]
    for min_w, f, days in table:
        if weight_kg >= min_w:
            fee, eta = f, days
    return fee, eta
