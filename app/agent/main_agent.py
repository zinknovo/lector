"""Assembly and execution entrypoint for the main AgentLoop."""

import asyncio
import json
from typing import Any

from langgraph.prebuilt import create_react_agent

from app.agent.llm import get_llm
from app.agent.middleware import post_step_compress
from app.agent.prompts import get_system_prompt
from app.agent.tool_registry import FULL_TOOL_SET
from app.api.context import set_thread_context
from app.api.monitor import monitor
from app.memory.store import store
from app.utils.path_utils import ensure_session_dir


MAIN_AGENT_MAX_ITERATIONS = 30
MAIN_AGENT_TIMEOUT_SEC = 300


def _build_main_agent(prompt: str):
    return create_react_agent(
        model=get_llm(),
        tools=FULL_TOOL_SET,
        prompt=prompt,
        pre_model_hook=post_step_compress,
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
                {"messages": [("user", query)]},
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
        return {"status": "timeout", "thread_id": thread_id}

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
    await monitor.report_task_result(final_text)
    return {"status": "ok", "thread_id": thread_id, "final": final_text}

