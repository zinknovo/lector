import asyncio
import importlib
import sys
from types import ModuleType

from langchain_core.messages import AIMessage

from app.api.context import get_thread_id, thread_scope


def _load_dispatch_module(monkeypatch):
    fake_tools = ModuleType("app.agent.tools")
    fake_tools.FULL_TOOL_SET = []
    monkeypatch.setitem(sys.modules, "app.agent.tools", fake_tools)
    sys.modules.pop("app.agent.dispatch_tool", None)
    module = importlib.import_module("app.agent.dispatch_tool")
    monkeypatch.setattr(module, "get_llm", lambda: object())
    return module


def test_dispatch_sets_depth_recursion_limit_and_restores_context(monkeypatch, tmp_path) -> None:
    module = _load_dispatch_module(monkeypatch)
    fake_registry = ModuleType("app.agent.tool_registry")
    fake_registry.FULL_TOOL_SET = []
    monkeypatch.setitem(sys.modules, "app.agent.tool_registry", fake_registry)

    class FakeAgent:
        config = None

        async def ainvoke(self, _state, config):
            self.config = config
            assert get_thread_id().endswith("-d1")
            return {"messages": [AIMessage(content="完成")]}

    fake_agent = FakeAgent()
    monkeypatch.setattr(module, "create_react_agent", lambda **_kwargs: fake_agent)

    async def run():
        with thread_scope("parent", tmp_path):
            result = await module.dispatch_tool.ainvoke({"demands": "查商品"})
            assert get_thread_id() == "parent"
            return result

    assert asyncio.run(run()) == "完成"
    assert fake_agent.config["recursion_limit"] == 12


def test_dispatch_returns_readable_message_at_fork_limit(monkeypatch, tmp_path) -> None:
    module = _load_dispatch_module(monkeypatch)
    fake_registry = ModuleType("app.agent.tool_registry")
    fake_registry.FULL_TOOL_SET = []
    monkeypatch.setitem(sys.modules, "app.agent.tool_registry", fake_registry)
    from app.agent.fork_guard import enter_fork

    async def run():
        with thread_scope("parent", tmp_path):
            with enter_fork(), enter_fork():
                return await module.dispatch_tool.ainvoke({"demands": "继续派发"})

    assert "[dispatch_tool 拒绝]" in asyncio.run(run())


def test_dispatch_returns_readable_message_on_timeout(monkeypatch, tmp_path) -> None:
    module = _load_dispatch_module(monkeypatch)
    fake_registry = ModuleType("app.agent.tool_registry")
    fake_registry.FULL_TOOL_SET = []
    monkeypatch.setitem(sys.modules, "app.agent.tool_registry", fake_registry)

    class SlowAgent:
        async def ainvoke(self, _state, config):
            await asyncio.sleep(0.05)

    monkeypatch.setattr(module, "create_react_agent", lambda **_kwargs: SlowAgent())
    monkeypatch.setattr(module, "SUB_AGENT_TIMEOUT_SEC", 0.001, raising=False)

    async def run():
        with thread_scope("parent", tmp_path):
            return await module.dispatch_tool.ainvoke({"demands": "慢任务"})

    assert "[dispatch_tool 超时]" in asyncio.run(run())
