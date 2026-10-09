"""按线程分发 monitor 事件给运行观察者（AG-UI 投影层使用）。

对应参考工程的 ``observe_run_events``：AG-UI 适配器进入该上下文后，
本线程的每个 monitor 事件都会同时送达观察者，WS 分发路径不受影响。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

Observer = Callable[[dict[str, object]], None]

_observers: dict[str, list[Observer]] = {}


@contextmanager
def observe_thread_events(thread_id: str, callback: Observer) -> Iterator[None]:
    callbacks = _observers.setdefault(thread_id, [])
    callbacks.append(callback)
    try:
        yield
    finally:
        if callback in callbacks:
            callbacks.remove(callback)
        if not callbacks:
            _observers.pop(thread_id, None)


def notify_thread_events(thread_id: str, payload: dict[str, object]) -> None:
    for callback in list(_observers.get(thread_id, ())):
        callback(payload)
