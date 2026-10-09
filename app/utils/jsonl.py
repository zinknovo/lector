"""JSONL 读写的宽容实现：坏行跳过，写入即追加一行。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def iter_jsonl(path: Path) -> Iterator[Any]:
    """逐行读取 JSONL；空行与损坏行跳过，不阻塞读取。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            yield json.loads(stripped)
        except ValueError:
            continue


def append_jsonl(path: Path, payload: Any) -> None:
    """追加一行 JSON（自动建目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str))
        handle.write("\n")
