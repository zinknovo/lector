"""候选被排除的统一结构：让卖家能看到"为什么没进推荐"。"""

from typing import Literal

from pydantic import BaseModel

ExclusionReason = Literal[
    "preference_hard_fail",
    "not_top_n",
    "category_mismatch",
]


class ExcludedCandidate(BaseModel):
    """被排除的候选及其原因码。"""

    item_id: str
    platform: str
    reason_code: ExclusionReason
    reason: str
