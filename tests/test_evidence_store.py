"""证据库：写入、读取、过滤、容错与无上下文降级。"""

from pathlib import Path

from app.api.context import thread_scope
from app.evidence.models import EvidenceItem, EvidenceMethod
from app.evidence.store import EvidenceStore, get_evidence_store, record_evidence


def _store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "evidence.jsonl")


class TestRoundtrip:
    def test_record_and_list_preserves_fields(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        item = store.record(
            field="procurement_cost_cny",
            value=32.5,
            method=EvidenceMethod.EXTRACTED,
            source="web_search",
            detail="1688 搜索结果 | https://example.com/1",
            confidence=0.7,
            tool="procurement_quote",
            product_id="A1",
        )
        assert item.observed_at.endswith("Z")
        items = store.list()
        assert len(items) == 1
        loaded = items[0]
        assert loaded.field == "procurement_cost_cny"
        assert loaded.value == 32.5
        assert loaded.method is EvidenceMethod.EXTRACTED
        assert loaded.confidence == 0.7
        assert loaded.product_id == "A1"

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        _store(tmp_path).record(
            field="selling_price_cny",
            value=199,
            method=EvidenceMethod.EXTRACTED,
            source="market_price_search",
        )
        again = _store(tmp_path).list()
        assert [i.value for i in again] == [199]

    def test_latest_returns_last_write(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.record(
            field="procurement_cost_cny",
            value=10,
            method=EvidenceMethod.ESTIMATED,
            source="retail_ratio_estimate",
        )
        store.record(
            field="procurement_cost_cny",
            value=12.5,
            method=EvidenceMethod.EXTRACTED,
            source="web_search",
        )
        latest = store.latest(field="procurement_cost_cny")
        assert latest is not None
        assert latest.value == 12.5
        assert latest.method is EvidenceMethod.EXTRACTED


class TestFilters:
    def test_filter_by_field_and_product(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.record(
            field="procurement_cost_cny",
            value=1,
            method=EvidenceMethod.MEASURED,
            source="s",
            product_id="A1",
        )
        store.record(
            field="selling_price_cny",
            value=2,
            method=EvidenceMethod.MEASURED,
            source="s",
            product_id="A1",
        )
        store.record(
            field="procurement_cost_cny",
            value=3,
            method=EvidenceMethod.MEASURED,
            source="s",
            product_id="B2",
        )
        assert [i.value for i in store.list(field="procurement_cost_cny")] == [1, 3]
        assert [
            i.value for i in store.list(product_id="A1")
        ] == [1, 2]
        assert [
            i.value
            for i in store.list(field="procurement_cost_cny", product_id="A1")
        ] == [1]

    def test_filter_by_tool(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.record(
            field="exchange_rate",
            value=7.1,
            method=EvidenceMethod.MEASURED,
            source="web_search",
            tool="exchange_rate",
        )
        store.record(
            field="landed_cost_cny",
            value=9.9,
            method=EvidenceMethod.TABLE,
            source="cost_tables",
            tool="shipping_calc",
        )
        assert [i.value for i in store.list(tool="shipping_calc")] == [9.9]


class TestTolerance:
    def test_corrupt_line_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "evidence.jsonl"
        store = EvidenceStore(path)
        store.record(
            field="a", value=1, method=EvidenceMethod.MEASURED, source="s"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        store.record(
            field="b", value=2, method=EvidenceMethod.MEASURED, source="s"
        )
        assert [i.field for i in store.list()] == ["a", "b"]

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert EvidenceStore(tmp_path / "nope.jsonl").list() == []


class TestContextBinding:
    def test_record_evidence_uses_session_dir(self, tmp_path: Path) -> None:
        with thread_scope("t1", tmp_path):
            item = record_evidence(
                field="procurement_cost_cny",
                value=5,
                method=EvidenceMethod.ESTIMATED,
                source="retail_ratio_estimate",
            )
            assert item is not None
            assert (tmp_path / "evidence.jsonl").exists()
        assert get_evidence_store() is None  # 离开作用域后无上下文

    def test_record_evidence_without_context_is_noop(self) -> None:
        assert (
            record_evidence(
                field="x", value=1, method=EvidenceMethod.MISSING, source="s"
            )
            is None
        )


class TestLabel:
    def test_label_renders_method_and_confidence(self) -> None:
        item = EvidenceItem(
            field="procurement_cost_cny",
            value=32.5,
            method=EvidenceMethod.ESTIMATED,
            source="retail_ratio_estimate",
            confidence=0.4,
            observed_at="2026-10-09T00:00:00Z",
        )
        label = item.label()
        assert "procurement_cost_cny=32.5" in label
        assert "估算" in label
        assert "置信度 0.40" in label

    def test_label_without_value_shows_field_only(self) -> None:
        item = EvidenceItem(
            field="procurement_cost_cny",
            method=EvidenceMethod.MISSING,
            source="unavailable",
            observed_at="2026-10-09T00:00:00Z",
        )
        assert item.label().startswith("procurement_cost_cny | 缺失")
