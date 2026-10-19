"""熔断器并发语义：同一工具并发调用时只放行一次半开探测，过期结果不关闭熔断。"""

import asyncio
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from app.agent.breaker import ToolCircuitBreaker
from app.agent.harness import HarnessMiddleware


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _request(call_id: str, name: str = "web_search") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": {}, "id": call_id, "type": "tool_call"},
        tool=None,
        state=None,
        runtime=None,
    )


def _middleware(clock: FakeClock) -> HarnessMiddleware:
    breaker = ToolCircuitBreaker(threshold=1, cooldown_seconds=60.0, clock=clock)
    return HarnessMiddleware(enable_drift=False, breaker=breaker)


def _tool_message(content: str, request: ToolCallRequest) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=str(request.tool_call["id"]),
        name="web_search",
    )


def test_stale_success_cannot_close_a_reopened_circuit() -> None:
    clock = FakeClock()
    middleware = _middleware(clock)
    started = asyncio.Event()
    release = asyncio.Event()

    async def stale_handler(request: ToolCallRequest) -> Any:
        started.set()
        await release.wait()
        return _tool_message("ok", request)

    async def failing_handler(request: ToolCallRequest) -> Any:
        return _tool_message("[error] upstream down", request)

    async def rejected_handler(request: ToolCallRequest) -> Any:
        raise AssertionError("熔断期内工具不应再执行")

    async def scenario() -> str:
        stale = asyncio.create_task(
            middleware.awrap_tool_call(_request("stale"), stale_handler)
        )
        await started.wait()
        await middleware.awrap_tool_call(_request("fail"), failing_handler)
        release.set()
        await stale
        result = await middleware.awrap_tool_call(_request("after"), rejected_handler)
        return str(result.content)

    assert "熔断" in asyncio.run(scenario())


def test_only_one_half_open_probe_runs() -> None:
    clock = FakeClock()
    middleware = _middleware(clock)
    started = asyncio.Event()
    release = asyncio.Event()
    probes: list[str] = []

    async def failing_handler(request: ToolCallRequest) -> Any:
        return _tool_message("[error] upstream down", request)

    async def first_probe(request: ToolCallRequest) -> Any:
        probes.append(str(request.tool_call["id"]))
        started.set()
        await release.wait()
        return _tool_message("ok", request)

    async def second_probe(request: ToolCallRequest) -> Any:
        probes.append(str(request.tool_call["id"]))
        return _tool_message("ok", request)

    async def scenario() -> str:
        await middleware.awrap_tool_call(_request("open"), failing_handler)
        clock.advance(61)
        first = asyncio.create_task(
            middleware.awrap_tool_call(_request("probe-1"), first_probe)
        )
        await started.wait()
        second = await middleware.awrap_tool_call(_request("probe-2"), second_probe)
        release.set()
        await first
        return str(second.content)

    result = asyncio.run(scenario())
    assert probes == ["probe-1"]
    assert "熔断" in result


def test_raising_handler_releases_the_probe_slot() -> None:
    clock = FakeClock()
    breaker = ToolCircuitBreaker(threshold=1, cooldown_seconds=0.0, clock=clock)
    middleware = HarnessMiddleware(enable_drift=False, breaker=breaker)
    calls: list[str] = []

    async def failing_handler(request: ToolCallRequest) -> Any:
        return _tool_message("[error] upstream down", request)

    async def raising_handler(request: ToolCallRequest) -> Any:
        calls.append("raise")
        raise RuntimeError("handler blew up")

    async def ok_handler(request: ToolCallRequest) -> Any:
        calls.append("ok")
        return _tool_message("ok", request)

    async def scenario() -> str:
        await middleware.awrap_tool_call(_request("open"), failing_handler)
        try:
            await middleware.awrap_tool_call(_request("boom"), raising_handler)
        except RuntimeError:
            pass
        result = await middleware.awrap_tool_call(_request("after"), ok_handler)
        return str(result.content)

    result = asyncio.run(scenario())
    assert calls == ["raise", "ok"]
    assert "熔断" not in result
