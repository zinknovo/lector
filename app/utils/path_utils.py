"""Path utilities for project directories and safe path joining."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_ROOT = PROJECT_ROOT / "uploaded"
OUTPUT_ROOT = PROJECT_ROOT / "output"
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def validate_thread_id(thread_id: str) -> str:
    """Return a safe thread identifier or raise ``ValueError``."""
    if not _THREAD_ID_RE.fullmatch(thread_id):
        raise ValueError("thread_id 只能包含字母、数字、下划线和连字符")
    return thread_id


def validate_filename(filename: str) -> str:
    """Reject empty names, control bytes and path components."""
    if (
        not filename
        or filename in {".", ".."}
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
    ):
        raise ValueError("文件名不合法")
    return filename


def ensure_session_dir(thread_id: str) -> Path:
    """获取或创建本次任务的输出目录。"""
    session_dir = OUTPUT_ROOT / validate_thread_id(thread_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def ensure_upload_dir(thread_id: str) -> Path:
    """获取或创建本次任务的上传目录。"""
    upload_dir = UPLOAD_ROOT / validate_thread_id(thread_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def safe_join(base: Path, *parts: str) -> Path:
    """防止 ../../ 越权访问的拼路径。"""
    target = (base / Path(*parts)).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"路径越权: {target}") from exc
    return target
