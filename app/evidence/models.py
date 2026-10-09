"""证据记录模型：说明每个关键数字是从哪里、怎么得到的。"""

from enum import Enum

from pydantic import BaseModel, Field


# 约定字段名（与工具输出字段对齐；决策与报告按这些名字取证据）：
#   procurement_cost_cny   <- procurement_quote
#   selling_price_evidence <- market_price_search
#   exchange_rate          <- exchange_rate
#   landed_cost_cny        <- shipping_calc（按 product_id）


class EvidenceMethod(str, Enum):
    """一条证据的取得方式，决定它在报告中的可信口径。"""

    MEASURED = "measured"    # 工具或服务直接返回的实测值
    EXTRACTED = "extracted"  # 从证据文本中提取（如从 1688 搜索结果提取价格）
    ESTIMATED = "estimated"  # 按比例推算（如按售价比例估算采购价）
    TABLE = "table"          # 查表或快照（成本表、税率、汇率）
    MISSING = "missing"      # 缺失，报告中必须显式标注


METHOD_LABELS: dict[EvidenceMethod, str] = {
    EvidenceMethod.MEASURED: "实测",
    EvidenceMethod.EXTRACTED: "提取",
    EvidenceMethod.ESTIMATED: "估算",
    EvidenceMethod.TABLE: "查表",
    EvidenceMethod.MISSING: "缺失",
}


class EvidenceItem(BaseModel):
    """一条数值证据；``field`` 建议与输出字段同名，便于报告对齐。"""

    field: str
    value: str | float | int | None = None
    method: EvidenceMethod
    source: str
    detail: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_at: str
    tool: str = ""
    product_id: str | None = None

    def label(self) -> str:
        """面向卖家的一句话口径说明，例如：采购价=32.5 | 提取 | 1688 搜索。"""
        parts: list[str] = []
        if self.value is not None:
            parts.append(f"{self.field}={self.value}")
        else:
            parts.append(self.field)
        parts.append(METHOD_LABELS[self.method])
        parts.append(self.source)
        if self.confidence is not None:
            parts.append(f"置信度 {self.confidence:.2f}")
        return " | ".join(parts)
