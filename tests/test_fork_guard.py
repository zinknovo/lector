import asyncio

import pytest

from app.agent.fork_guard import (
    ForkLimitExceeded,
    current_fork_depth,
    enter_fork,
)


def test_nested_forks_are_limited_and_depth_is_restored() -> None:
    assert current_fork_depth() == 0

    with enter_fork() as first:
        assert first == 1
        with enter_fork() as second:
            assert second == 2
            with pytest.raises(ForkLimitExceeded):
                with enter_fork():
                    pass

    assert current_fork_depth() == 0


def test_fork_depth_is_restored_after_exception() -> None:
    with pytest.raises(RuntimeError):
        with enter_fork():
            raise RuntimeError("boom")

    assert current_fork_depth() == 0


def test_fork_depth_is_isolated_between_async_tasks() -> None:
    async def worker() -> tuple[int, int]:
        with enter_fork() as depth:
            await asyncio.sleep(0)
            return depth, current_fork_depth()

    async def run():
        return await asyncio.gather(worker(), worker())

    assert asyncio.run(run()) == [(1, 1), (1, 1)]
    assert current_fork_depth() == 0

