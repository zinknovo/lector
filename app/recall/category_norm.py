"""品类名标准化：多源别名映射到统一标准名。"""

# 线下人工 + 商品图谱维护，通常几百条
CATEGORY_ALIASES: dict[str, str] = {
    "旅行收纳": "旅行三件套",
    "便携收纳包": "旅行三件套",
    "出差三件套": "旅行三件套",
    "咖啡杯": "咖啡杯",
    "马克杯": "咖啡杯",
}


def normalize_category(raw: str) -> str:
    raw = raw.strip().lower()
    return CATEGORY_ALIASES.get(raw, raw)
