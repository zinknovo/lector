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
from app.api.context import set_thread_context
from app.api.monitor import monitor
from app.memory.store import store
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

    long_term = (
        await store.read_relevant(user_id=user_id, query=query)
        if user_id
        else []
    )
    pref_text = "\n".join(f"- {preference.text}" for preference in long_term)
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
    additional = getattr(final_message, "additional_kwargs", {})
    new_preferences = additional.get("learned_preferences", [])
    if not isinstance(new_preferences, list):
        new_preferences = []
    clean_preferences = [
        str(preference) for preference in new_preferences if str(preference).strip()
    ]
    if user_id and clean_preferences:
        await store.write_many(user_id=user_id, texts=clean_preferences)

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

