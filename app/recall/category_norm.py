"""品类名标准化：多源别名映射到统一标准名。"""

# 线下人工 + 商品图谱维护，通常几百条
CATEGORY_ALIASES: dict[str, str] = {
    "旅行收纳": "旅行三件套",
    "便携收纳包": "旅行三件套",
    "出差三件套": "旅行三件套",
    "咖啡杯": "咖啡杯",
    "马克杯": "咖啡杯",
    # 耳机：中文口语/别名 → 标准品类
    "蓝牙耳机": "wireless earbuds",
    "无线耳机": "wireless earbuds",
    "真无线耳机": "wireless earbuds",
    "tws耳机": "wireless earbuds",
    # 背包
    "旅行背包": "travel backpack",
    "户外背包": "travel backpack",
    "双肩包": "travel backpack",
    # 颈枕
    "u型枕": "颈枕",
    "护颈枕": "颈枕",
    "旅行枕": "颈枕",
    "飞机枕": "颈枕",
    # 保温杯
    "保温水杯": "保温杯",
    "水杯": "保温杯",
    # 手机壳
    "手机套": "手机壳",
    # 露营灯
    "户外灯": "露营灯",
}


def normalize_category(raw: str) -> str:
    raw = raw.strip().lower()
    return CATEGORY_ALIASES.get(raw, raw)
