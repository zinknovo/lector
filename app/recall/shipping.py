"""按平台 + 重量分档的简化运费表（CNY）。"""

# platform: [(min_weight_kg, fee_cny, eta_days), ...]
SHIPPING_TABLE: dict[str, list[tuple[float, float, int]]] = {
    "amazon": [(0, 85, 12), (0.5, 130, 10), (2.0, 240, 8)],
    "shopee": [(0, 35, 9), (0.5, 60, 9), (2.0, 120, 7)],
    "aliexpress": [(0, 20, 25), (0.5, 40, 22), (2.0, 90, 18)],
    "ebay": [(0, 90, 14), (0.5, 150, 12), (2.0, 300, 10)],
}


def estimate_shipping(weight_kg: float, platform: str) -> tuple[float, int]:
    """根据重量和平台估算运费和物流时效。"""
    table = SHIPPING_TABLE.get(platform, SHIPPING_TABLE["amazon"])
    fee, eta = table[0][1], table[0][2]
    for min_w, f, days in table:
        if weight_kg >= min_w:
            fee, eta = f, days
    return fee, eta
