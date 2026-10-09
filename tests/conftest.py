"""测试隔离：把会话 / 上传目录重定向到临时目录，避免写进仓库的 output/。"""

import pytest

from app.utils import path_utils


@pytest.fixture(autouse=True)
def _isolated_app_dirs(tmp_path, monkeypatch):
    output_root = tmp_path / "output"
    upload_root = tmp_path / "uploaded"
    output_root.mkdir()
    upload_root.mkdir()
    monkeypatch.setattr(path_utils, "OUTPUT_ROOT", output_root)
    monkeypatch.setattr(path_utils, "UPLOAD_ROOT", upload_root)
    yield
