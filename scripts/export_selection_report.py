"""Export a ShoppingSummaryOutput JSON document as PDF and XLSX."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.reports import export_selection_report
from app.tools.shopping_summary import ShoppingSummaryOutput


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a Lector selection report")
    parser.add_argument("input", type=Path, help="ShoppingSummaryOutput JSON file")
    parser.add_argument("--output-dir", type=Path, default=Path("output/reports"))
    parser.add_argument("--basename", default="selection-report")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    summary = ShoppingSummaryOutput.model_validate(payload)
    exported = export_selection_report(summary, args.output_dir, args.basename)
    print(exported.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
