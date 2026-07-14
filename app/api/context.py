from collections.abc import Generator
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path

# 当前请求的 thread_id（由 /api/task 入口设置）
_thread_id_var: ContextVar[str | None] = ContextVar(
    "globex_thread_id", default=None
)

# 当前请求的会话目录（输出文件落到这里）
_session_dir_var: ContextVar[Path | None] = ContextVar(
    "globex_session_dir", default=None
)


def set_thread_context(thread_id: str, session_dir: Path) -> None:
    """请求入口处调用，写入本次任务的身份信息。"""
    _ = _thread_id_var.set(thread_id)
    _ = _session_dir_var.set(session_dir)


def get_thread_id() -> str | None:
    return _thread_id_var.get()


def get_session_dir() -> Path | None:
    return _session_dir_var.get()


@contextmanager
def thread_scope(thread_id: str, session_dir: Path) -> Generator[None, None, None]:
    """作用域内绑定 thread_id 与 session_dir，离开作用域自动还原。"""
    token_t = _thread_id_var.set(thread_id)
    token_s = _session_dir_var.set(session_dir)
    try:
        yield
    finally:
        _thread_id_var.reset(token_t)
        _session_dir_var.reset(token_s)
