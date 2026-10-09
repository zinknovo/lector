"""Assembly and execution entrypoint for the main AgentLoop."""

import asyncio
import json
import os
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from app.agent.harness import build_harness_middleware
from app.agent.llm import get_llm
from app.agent.prompts import get_system_prompt
from app.agent.tool_registry import FULL_TOOL_SET
from app.api.context import set_thread_context, set_user_context
from app.api.monitor import monitor
from app.memory.store import (
    PreferenceConflict,
    PreferenceKind,
    PreferenceStoreError,
    store,
)
from app.security.guards import audit_output
from app.utils.path_utils import ensure_session_dir


MAIN_AGENT_MAX_ITERATIONS = 45
# 真实链路含 Apify + DeepSeek web_search，单次搜索常 30–60s；默认放宽到 10 分钟
MAIN_AGENT_TIMEOUT_SEC = int(os.environ.get("MAIN_AGENT_TIMEOUT_SEC", "600"))


def _build_main_agent(prompt: str):
    """主 Agent 装配：业务工具 + Harness 中间件（工具边界与轮次边界护栏）。"""
    return create_agent(
        model=get_llm(),
        tools=FULL_TOOL_SET,
        system_prompt=prompt,
        middleware=[build_harness_middleware()],
    )


# 负向偏好的口语前缀：报告里回传的偏好按此推断 like / dislike
_DISLIKE_PREFIXES = ("不要", "避免", "避开", "排除", "不喜欢", "禁用")


def infer_preference_kind(statement: str) -> PreferenceKind:
    """偏好的正负向推断（报告回传的是纯文本，模型按提示词以「不要/避免…」开头）。"""
    cleaned = statement.strip()
    return (
        "dislike"
        if cleaned.startswith(_DISLIKE_PREFIXES)
        else "like"
    )


def extract_learned_preferences(messages: list[Any]) -> list[str]:
    """从最后一条 shopping_summary 工具输出里取 learned_preferences。"""
    for message in reversed(messages):
        if getattr(message, "type", "") != "tool":
            continue
        if getattr(message, "name", "") != "shopping_summary":
            continue
        content = message.content
        if not isinstance(content, str):
            return []
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return []
        preferences = (
            payload.get("learned_preferences") if isinstance(payload, dict) else None
        )
        if not isinstance(preferences, list):
            return []
        return [
            str(preference).strip()
            for preference in preferences
            if str(preference).strip()
        ]
    return []


async def persist_learned_preferences(
    user_id: str | None, messages: list[Any]
) -> None:
    """把报告里明确要求记住的偏好落库；冲突/失败只记事件，不打断任务。"""
    if not user_id:
        return
    for statement in extract_learned_preferences(messages):
        try:
            await store.add(
                user_id,
                kind=infer_preference_kind(statement),
                statement=statement,
                source="report",
            )
        except (PreferenceConflict, PreferenceStoreError) as exc:
            await monitor.report_event(
                "preference_not_saved",
                f"偏好未保存：{exc}",
                {"statement": statement},
            )


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


async def run_agent(
    query: str,
    thread_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """主 AgentLoop 的入口。"""
    session_dir = ensure_session_dir(thread_id)
    set_thread_context(thread_id, session_dir)
    set_user_context(user_id)

    preferences = await store.list_by_buyer(user_id) if user_id else []
    pref_text = "\n".join(
        f"- [{preference.kind}] {preference.statement}"
        for preference in preferences
    )
    pref_text = pref_text or "（暂无沉淀偏好）"
    prompt = get_system_prompt(long_term_preferences=pref_text)
    agent = _build_main_agent(prompt)

    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=query)]},
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": MAIN_AGENT_MAX_ITERATIONS,
                },
            ),
            timeout=MAIN_AGENT_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        await monitor.report_error(
            "timeout", f"主任务超时 {MAIN_AGENT_TIMEOUT_SEC}s"
        )
        await monitor.report_event(
            "task_incomplete",
            f"任务在 {MAIN_AGENT_TIMEOUT_SEC}s 上限处停止，未完成全部核验；"
            "已产出的中间结果保留在执行记录中，不会补写未核验的数据",
            {"reason": "timeout", "limit_sec": MAIN_AGENT_TIMEOUT_SEC},
        )
        return {"status": "timeout", "thread_id": thread_id}
    except GraphRecursionError:
        await monitor.report_error(
            "iteration_limit", f"达到迭代上限 {MAIN_AGENT_MAX_ITERATIONS}"
        )
        await monitor.report_event(
            "task_incomplete",
            f"达到迭代上限（{MAIN_AGENT_MAX_ITERATIONS} 步），未完成全部核验；"
            "请缩小选品范围或基于已有证据重新发起",
            {"reason": "iteration_limit", "limit": MAIN_AGENT_MAX_ITERATIONS},
        )
        return {"status": "iteration_limit", "thread_id": thread_id}

    final_message = result["messages"][-1]
    await persist_learned_preferences(user_id, result["messages"])

    final_text = _message_text(final_message.content)
    safe, final_text = audit_output(final_text)
    if not safe:
        await monitor.report_event(
            "output_audit",
            "最终回复命中敏感模式（密钥/内部地址/本机路径），已脱敏后下发",
            {"status": "redacted"},
        )
    await monitor.report_task_result(final_text)
    return {"status": "ok", "thread_id": thread_id, "final": final_text}

