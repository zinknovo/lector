from pathlib import Path

import pytest

from app.utils import path_utils


@pytest.mark.parametrize("thread_id", ["abc123", "thread-123", "thread_123"])
def test_validate_thread_id_accepts_safe_identifiers(thread_id: str) -> None:
    assert path_utils.validate_thread_id(thread_id) == thread_id


@pytest.mark.parametrize(
    "thread_id",
    ["", "../escape", "with/slash", "with space", ".hidden", "x" * 129],
)
def test_validate_thread_id_rejects_unsafe_identifiers(thread_id: str) -> None:
    with pytest.raises(ValueError):
        path_utils.validate_thread_id(thread_id)


@pytest.mark.parametrize("filename", ["image.png", "报告 2026.pdf", "a-b_c.webp"])
def test_validate_filename_accepts_plain_names(filename: str) -> None:
    assert path_utils.validate_filename(filename) == filename


@pytest.mark.parametrize("filename", ["", ".", "..", "../x", "a/b", "a\\b", "\x00.png"])
def test_validate_filename_rejects_paths_and_empty_names(filename: str) -> None:
    with pytest.raises(ValueError):
        path_utils.validate_filename(filename)


def test_safe_join_stays_within_base(tmp_path: Path) -> None:
    assert path_utils.safe_join(tmp_path, "nested", "file.txt") == (
        tmp_path / "nested" / "file.txt"
    ).resolve()


def test_safe_join_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        path_utils.safe_join(tmp_path, "..", "escape.txt")


def test_safe_join_rejects_prefix_confusion(tmp_path: Path) -> None:
    base = tmp_path / "session"
    sibling = tmp_path / "session-escape" / "file.txt"

    with pytest.raises(ValueError):
        path_utils.safe_join(base, str(sibling))
