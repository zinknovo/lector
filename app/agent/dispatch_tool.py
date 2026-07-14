"""Tool that dispatches work to a guarded sub-agent loop."""

import asyncio
from uuid import uuid4

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.agent.fork_guard import ForkLimitExceeded, enter_fork
from app.agent.llm import get_llm
from app.agent.prompts import get_system_prompt
from app.api.context import _session_dir_var, _thread_id_var, get_session_dir
from app.api.monitor import monitor


SUB_AGENT_TIMEOUT_SEC = 90
SUB_AGENT_MAX_ITERATIONS = 12


@tool
async def dispatch_tool(demands: str) -> str:
    """派一个同质子 AgentLoop 去执行 demands，返回它的最终回复。

    适用条件（任一即可）：
    1. 能并行：多个子任务可以同时跑
    2. 上下文要隔离：子任务输出很大，不应污染主 loop
    3. 调用链 ≥ 3：子任务自己内部还要多轮 Think → Act
    """
    try:
        with enter_fork() as depth:
            from app.agent.tool_registry import FULL_TOOL_SET

            sub_thread_id = f"sub-{uuid4().hex[:8]}-d{depth}"
            await monitor.report_fork(sub_thread_id, demands)

            sub_agent = create_react_agent(
                model=get_llm(),
                tools=FULL_TOOL_SET,
                prompt=get_system_prompt(),
            )

            parent_session_dir = get_session_dir()
            if parent_session_dir is None:
                raise RuntimeError(
                    "dispatch_tool must be called within a thread scope"
                )

            token_t = _thread_id_var.set(sub_thread_id)
            token_s = _session_dir_var.set(parent_session_dir)
            try:
                result = await asyncio.wait_for(
                    sub_agent.ainvoke(
                        {"messages": [("user", demands)]},
                        config={
                            "configurable": {"thread_id": sub_thread_id},
                            "recursion_limit": SUB_AGENT_MAX_ITERATIONS,
                        },
                    ),
                    timeout=SUB_AGENT_TIMEOUT_SEC,
                )
                content = result["messages"][-1].content
                return content if isinstance(content, str) else str(content)
            finally:
                _thread_id_var.reset(token_t)
                _session_dir_var.reset(token_s)
    except ForkLimitExceeded as error:
        return (
            f"[dispatch_tool 拒绝]：{error}。"
            "建议主 loop 自己处理或换一种拆分。"
        )
    except asyncio.TimeoutError:
        return (
            f"[dispatch_tool 超时]：子任务 {SUB_AGENT_TIMEOUT_SEC}s 未完成"
        )
