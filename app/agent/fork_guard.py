"""Context-local guard against recursive sub-agent dispatch."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar


_fork_depth: ContextVar[int] = ContextVar("globex_fork_depth", default=0)
MAX_FORK_DEPTH = 2


class ForkLimitExceeded(Exception):
    pass


@contextmanager
def enter_fork() -> Generator[int, None, None]:
    current = _fork_depth.get()
    if current >= MAX_FORK_DEPTH:
        raise ForkLimitExceeded(f"fork 深度超过上限 {MAX_FORK_DEPTH}")
    token = _fork_depth.set(current + 1)
    try:
        yield current + 1
    finally:
        _fork_depth.reset(token)


def current_fork_depth() -> int:
    return _fork_depth.get()

