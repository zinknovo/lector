"""会话级证据库：按线程记录工具产出的证据，决策与报告从这里取来源。

存储格式为会话目录下的 ``evidence.jsonl``，一行一条、追加写。
没有会话上下文（离线脚本、单元测试）时写入静默跳过，与
``monitor`` / ``ProductSearchCache`` 的降级方式保持一致。
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.api.context import get_session_dir
from app.evidence.models import EvidenceItem, EvidenceMethod

EVIDENCE_FILENAME = "evidence.jsonl"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class EvidenceStore:
    """线程内共享的证据库；JSONL 追加写、全量读，会话量级足够。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(
        self,
        *,
        field: str,
        method: EvidenceMethod,
        source: str,
        value: str | float | int | None = None,
        detail: str = "",
        confidence: float | None = None,
        tool: str = "",
        product_id: str | None = None,
    ) -> EvidenceItem:
        item = EvidenceItem(
            field=field,
            value=value,
            method=method,
            source=source,
            detail=detail,
            confidence=confidence,
            observed_at=utc_now(),
            tool=tool,
            product_id=product_id,
        )
        self.add(item)
        return item

    def add(self, item: EvidenceItem) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(item.model_dump_json())
            fh.write("\n")

    def list(
        self,
        *,
        field: str | None = None,
        product_id: str | None = None,
        tool: str | None = None,
    ) -> list[EvidenceItem]:
        """按写入顺序返回证据；损坏行跳过，不阻塞读取。"""
        if not self.path.exists():
            return []
        items: list[EvidenceItem] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = EvidenceItem.model_validate(json.loads(stripped))
            except ValueError:
                continue
            if field is not None and item.field != field:
                continue
            if product_id is not None and item.product_id != product_id:
                continue
            if tool is not None and item.tool != tool:
                continue
            items.append(item)
        return items

    def latest(
        self,
        *,
        field: str,
        product_id: str | None = None,
        tool: str | None = None,
    ) -> EvidenceItem | None:
        items = self.list(field=field, product_id=product_id, tool=tool)
        return items[-1] if items else None

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def get_evidence_store() -> EvidenceStore | None:
    """从会话上下文取证据库；无上下文时返回 ``None``。"""
    session_dir = get_session_dir()
    if session_dir is None:
        return None
    return EvidenceStore(session_dir / EVIDENCE_FILENAME)


def record_evidence(
    *,
    field: str,
    method: EvidenceMethod,
    source: str,
    value: str | float | int | None = None,
    detail: str = "",
    confidence: float | None = None,
    tool: str = "",
    product_id: str | None = None,
) -> EvidenceItem | None:
    """便捷入口：有会话上下文就落一条证据，否则静默跳过。"""
    store = get_evidence_store()
    if store is None:
        return None
    return store.record(
        field=field,
        method=method,
        source=source,
        value=value,
        detail=detail,
        confidence=confidence,
        tool=tool,
        product_id=product_id,
    )
