"""偏好工具：记住 / 撤回 / 冲突 / 上限，以及买家身份缺失与存储失败。"""

import asyncio

import pytest

from app.api.context import set_user_context
from app.memory.store import (
    MAX_PREFERENCES_PER_BUYER,
    InMemoryPreferenceStore,
    PreferenceStoreError,
)
from app.tools import preferences as module


@pytest.fixture(autouse=True)
def _reset_user():
    yield
    set_user_context(None)


def _use_store(monkeypatch, store) -> None:
    monkeypatch.setattr(module, "store", store)


def test_remember_saves_and_reports_duplicate(monkeypatch) -> None:
    _use_store(monkeypatch, InMemoryPreferenceStore())
    set_user_context("u1")

    first = asyncio.run(
        module.remember_preference.ainvoke({"statement": "默认做美国站"})
    )
    assert first.status == "saved"
    assert first.preference is not None
    assert first.preference.kind == "like"

    again = asyncio.run(
        module.remember_preference.ainvoke({"statement": "默认做美国站"})
    )
    assert again.status == "duplicate"


def test_remember_reports_conflict_with_opposite_kind(monkeypatch) -> None:
    _use_store(monkeypatch, InMemoryPreferenceStore())
    set_user_context("u1")
    asyncio.run(module.remember_preference.ainvoke({"statement": "用塑料材质"}))

    conflict = asyncio.run(
        module.remember_preference.ainvoke(
            {"statement": "用塑料材质", "kind": "dislike"}
        )
    )
    assert conflict.status == "conflict"
    assert "相反偏好" in conflict.message


def test_remember_without_buyer_identity_is_rejected(monkeypatch) -> None:
    _use_store(monkeypatch, InMemoryPreferenceStore())
    set_user_context(None)
    result = asyncio.run(module.remember_preference.ainvoke({"statement": "x"}))
    assert result.status == "error"


def test_remember_reports_store_failure(monkeypatch) -> None:
    class BrokenStore(InMemoryPreferenceStore):
        async def add(self, *args, **kwargs):
            raise PreferenceStoreError("偏好存储暂时不可用，未保存")

    _use_store(monkeypatch, BrokenStore())
    set_user_context("u1")
    result = asyncio.run(module.remember_preference.ainvoke({"statement": "x"}))
    assert result.status == "error"
    assert "未保存" in result.message


def test_forget_removes_exact_statement(monkeypatch) -> None:
    store = InMemoryPreferenceStore()
    _use_store(monkeypatch, store)
    set_user_context("u1")
    asyncio.run(module.remember_preference.ainvoke({"statement": "避开塑料"}))

    forgotten = asyncio.run(
        module.forget_preference.ainvoke({"statement": "避开塑料"})
    )
    assert forgotten.status == "forgotten"
    missing = asyncio.run(
        module.forget_preference.ainvoke({"statement": "避开塑料"})
    )
    assert missing.status == "not_found"


def test_remember_respects_limit(monkeypatch) -> None:
    _use_store(monkeypatch, InMemoryPreferenceStore())
    set_user_context("u1")
    for index in range(MAX_PREFERENCES_PER_BUYER):
        result = asyncio.run(
            module.remember_preference.ainvoke({"statement": f"偏好 {index}"})
        )
        assert result.status == "saved"
    overflow = asyncio.run(
        module.remember_preference.ainvoke({"statement": "再来一条"})
    )
    assert overflow.status == "error"
    assert "上限" in overflow.message
