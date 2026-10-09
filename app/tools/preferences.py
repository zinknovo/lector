"""记住 / 撤回跨会话偏好的工具（卖家明确表达才写入）。"""

from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel

from app.api.context import get_user_id
from app.api.monitor import monitor
from app.memory.store import (
    Preference,
    PreferenceConflict,
    PreferenceKind,
    PreferenceStoreError,
    store,
)


class PreferenceToolOutput(BaseModel):
    status: Literal[
        "saved", "duplicate", "conflict", "forgotten", "not_found", "error"
    ]
    message: str
    preference: Preference | None = None


@tool
async def remember_preference(
    statement: str,
    kind: PreferenceKind = "like",
) -> PreferenceToolOutput:
    """记住一条跨会话的选品偏好（如「默认做美国站」「毛利率低于 30% 不做」「避开塑料材质」）。

    只在卖家明确要求记住时调用；一次性要求（如"这次按日本站看"）不要保存。
    kind="dislike" 表示需要避免或排除的事项。
    """
    buyer_id = get_user_id()
    cleaned = statement.strip()
    if not buyer_id:
        return PreferenceToolOutput(status="error", message="缺少买家身份，未保存")
    if not cleaned:
        return PreferenceToolOutput(status="error", message="偏好内容为空，未保存")
    await monitor.report_tool_start("remember_preference", {"kind": kind})
    try:
        write = await store.add(
            buyer_id, kind=kind, statement=cleaned, source="tool"
        )
    except PreferenceConflict as exc:
        return PreferenceToolOutput(status="conflict", message=str(exc))
    except PreferenceStoreError as exc:
        return PreferenceToolOutput(status="error", message=str(exc))
    finally:
        await monitor.report_tool_end("remember_preference", 0)
    if write.created:
        return PreferenceToolOutput(
            status="saved",
            message=f"已记住：{write.preference.statement}",
            preference=write.preference,
        )
    return PreferenceToolOutput(
        status="duplicate",
        message=f"这条偏好已存在：{write.preference.statement}",
        preference=write.preference,
    )


@tool
async def forget_preference(statement: str) -> PreferenceToolOutput:
    """撤回一条已保存的长期偏好（按原句精确匹配；撤回后新会话不再引用）。"""
    buyer_id = get_user_id()
    cleaned = statement.strip()
    if not buyer_id:
        return PreferenceToolOutput(status="error", message="缺少买家身份，未撤回")
    if not cleaned:
        return PreferenceToolOutput(status="error", message="偏好内容为空，未撤回")
    await monitor.report_tool_start("forget_preference", {})
    try:
        removed = await store.forget(buyer_id, statement=cleaned)
    except PreferenceStoreError as exc:
        return PreferenceToolOutput(status="error", message=str(exc))
    finally:
        await monitor.report_tool_end("forget_preference", 0)
    if removed:
        return PreferenceToolOutput(
            status="forgotten", message=f"已撤回：{cleaned}"
        )
    return PreferenceToolOutput(
        status="not_found", message=f"没有找到这条偏好：{cleaned}"
    )
