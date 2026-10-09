"""会话 checkpoint：状态跨运行延续，打开失败时降级为无 checkpoint。"""

import asyncio
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.checkpoint import CHECKPOINT_FILENAME, open_checkpointer
from tests.test_harness import RecordingFakeModel


def test_state_continues_across_runs_in_same_thread(tmp_path: Path) -> None:
    async def scenario() -> list[list[str]]:
        seen: list[list[str]] = []
        async with open_checkpointer(tmp_path) as saver:
            assert saver is not None
            model = RecordingFakeModel(script=[AIMessage(content="第一次回答")])
            agent = create_agent(
                model=model, tools=[], middleware=[], checkpointer=saver
            )
            await agent.ainvoke(
                {"messages": [HumanMessage(content="第一个问题")]},
                config={"configurable": {"thread_id": "t1"}},
            )
            seen.append([str(message.content) for message in model.calls[0]])

            second = RecordingFakeModel(script=[AIMessage(content="第二次回答")])
            agent2 = create_agent(
                model=second, tools=[], middleware=[], checkpointer=saver
            )
            await agent2.ainvoke(
                {"messages": [HumanMessage(content="追问")]},
                config={"configurable": {"thread_id": "t1"}},
            )
            seen.append([str(message.content) for message in second.calls[0]])
        return seen

    first_call, second_call = asyncio.run(scenario())
    assert first_call == ["第一个问题"]
    # 第二次运行能看到上一次的问题与回答（同一 thread 延续）
    assert "第一个问题" in second_call
    assert "第一次回答" in second_call
    assert second_call[-1] == "追问"
    assert (tmp_path / CHECKPOINT_FILENAME).exists()


def test_distinct_threads_are_isolated(tmp_path: Path) -> None:
    async def scenario() -> list[str]:
        async with open_checkpointer(tmp_path) as saver:
            assert saver is not None
            model = RecordingFakeModel(script=[AIMessage(content="回答")])
            agent = create_agent(
                model=model, tools=[], middleware=[], checkpointer=saver
            )
            await agent.ainvoke(
                {"messages": [HumanMessage(content="线程 A")]},
                config={"configurable": {"thread_id": "a"}},
            )
            other = RecordingFakeModel(script=[AIMessage(content="回答")])
            agent2 = create_agent(
                model=other, tools=[], middleware=[], checkpointer=saver
            )
            await agent2.ainvoke(
                {"messages": [HumanMessage(content="线程 B")]},
                config={"configurable": {"thread_id": "b"}},
            )
            return [str(message.content) for message in other.calls[0]]
        return []

    assert asyncio.run(scenario()) == ["线程 B"]


def test_open_checkpointer_degrades_when_path_unusable(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file", encoding="utf-8")

    async def scenario():
        async with open_checkpointer(blocker) as saver:
            return saver

    assert asyncio.run(scenario()) is None
