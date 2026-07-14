"""品类知识库模型：存储经过提炼的品类洞察卡片。"""

from typing import Literal

from pydantic import BaseModel


class CategoryCard(BaseModel):
    """品类洞察卡片。"""

    card_id: str
    category: str  # 标准化的品类名，如 "旅行三件套"
    card_type: Literal["bestseller", "attribute", "price_range"]
    summary: str  # 已经提炼好的一段结论
    raw_evidence: list[str]  # 支撑这条结论的 1-3 段原始证据
    last_updated: str  # ISO 时间戳
    confidence: float  # 0-1 的置信度（来自数据 / 来自人工）
