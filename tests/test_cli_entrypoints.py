import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_direct_script_entrypoints_can_import_application() -> None:
    for script in (
        "scripts/smoke_external_services.py",
        "scripts/export_selection_report.py",
        "scripts/setup_pipeline.py",
        "scripts/build_category_kb.py",
    ):
        result = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
