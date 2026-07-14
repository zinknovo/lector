from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def file_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    from app.utils import path_utils

    upload_root = tmp_path / "uploaded"
    output_root = tmp_path / "output"
    monkeypatch.setattr(path_utils, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(path_utils, "OUTPUT_ROOT", output_root)
    return upload_root, output_root


def test_upload_accepts_supported_image(file_roots: tuple[Path, Path]) -> None:
    from app.api.server import app

    upload_root, _ = file_roots
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            params={"thread_id": "thread-1"},
            files={"file": ("reference.png", b"png-data", "image/png")},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "path": "uploaded/thread-1/reference.png",
    }
    assert (upload_root / "thread-1" / "reference.png").read_bytes() == b"png-data"


def test_upload_rejects_unsupported_type(file_roots: tuple[Path, Path]) -> None:
    from app.api.server import app

    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            params={"thread_id": "thread-1"},
            files={"file": ("notes.txt", b"text", "text/plain")},
        )

    assert response.status_code == 415


def test_upload_rejects_unsafe_filename(file_roots: tuple[Path, Path]) -> None:
    from app.api.server import app

    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            params={"thread_id": "thread-1"},
            files={"file": ("../escape.png", b"png-data", "image/png")},
        )

    assert response.status_code == 422


def test_upload_rejects_oversized_file_and_removes_partial_output(
    file_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import server

    upload_root, _ = file_roots
    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 4)
    with TestClient(server.app) as client:
        response = client.post(
            "/api/upload",
            params={"thread_id": "thread-1"},
            files={"file": ("large.png", b"12345", "image/png")},
        )

    assert response.status_code == 413
    assert not (upload_root / "thread-1" / "large.png").exists()


def test_download_returns_session_file(file_roots: tuple[Path, Path]) -> None:
    from app.api.server import app

    _, output_root = file_roots
    session = output_root / "thread-1"
    session.mkdir(parents=True)
    (session / "report.md").write_text("result", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/api/files/thread-1/report.md")

    assert response.status_code == 200
    assert response.content == b"result"
    assert "report.md" in response.headers["content-disposition"]


def test_download_rejects_directory(file_roots: tuple[Path, Path]) -> None:
    from app.api.server import app

    _, output_root = file_roots
    (output_root / "thread-1" / "directory").mkdir(parents=True)

    with TestClient(app) as client:
        response = client.get("/api/files/thread-1/directory")

    assert response.status_code == 404
    assert response.json() == {"detail": "文件不存在：directory"}
