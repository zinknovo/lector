"""把评测失败与候选案例合并成"待人工确认"的回归候选（教程 18 最小版）。

- 输入：`run_eval.py --failures-out` 的产物、`export_case.py` 的候选案例、或
  任何 `eval/cases` 同构文件；
- 指纹去重（inputs + expected 的规范化 JSON 哈希），并与现有用例集比对去重；
- 结构校验：id / inputs 必填，expected.recommendation 合法或留空（留空=待人工补）；
- 默认只报告（dry-run），`--write` 才把**完整且新增**的用例写到 `--out`
  （默认 `eval/failures/merged-cases.yaml`）。正式用例集仍由人工并入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

VALID_RECOMMENDATIONS = {"recommend", "watch", "reject"}


def fingerprint(case: dict[str, Any]) -> str:
    payload = json.dumps(
        {"inputs": case.get("inputs"), "expected": case.get("expected")},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_entries(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return [], [f"{path}: 文件结构不是映射"]
    for key in ("cases", "candidate_cases"):
        entries = data.get(key)
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)], []
    if "queries" in data:
        return [], [
            f"{path}: 召回失败查询（queries）不能并入决策用例；请人工转为 recall 标注"
        ]
    return [], [f"{path}: 未找到 cases / candidate_cases 列表"]


def _validate(
    case: dict[str, Any], source: Path
) -> tuple[bool, str]:
    if not isinstance(case.get("id"), str) or not case["id"].strip():
        return False, "缺少 id"
    if not isinstance(case.get("inputs"), dict):
        return False, f"{case.get('id')}: 缺少 inputs"
    expected = case.get("expected") or {}
    if not isinstance(expected, dict):
        return False, f"{case.get('id')}: expected 必须是映射"
    recommendation = expected.get("recommendation")
    if recommendation is not None and recommendation not in VALID_RECOMMENDATIONS:
        return False, f"{case.get('id')}: expected.recommendation 非法（{recommendation}）"
    return True, ""


def merge_cases(
    sources: list[Path],
    *,
    into: Path,
    out: Path,
    write: bool = False,
) -> dict[str, Any]:
    """合并候选；返回报告（新增 / 重复 / 不完整 / 非法）。"""
    existing = yaml.safe_load(into.read_text(encoding="utf-8")) or {}
    existing_fingerprints = {
        fingerprint(case)
        for case in (existing.get("cases") or [])
        if isinstance(case, dict)
    }

    report: dict[str, Any] = {
        "new_cases": [],
        "duplicates": [],
        "incomplete": [],
        "invalid": [],
        "notes": [],
    }
    seen: set[str] = set()

    for source in sources:
        entries, notes = _load_entries(source)
        report["notes"].extend(notes)
        for case in entries:
            ok, reason = _validate(case, source)
            if not ok:
                report["invalid"].append({"source": str(source), "reason": reason})
                continue
            expected = case.get("expected") or {}
            if not expected.get("recommendation"):
                report["incomplete"].append(
                    {"id": case["id"], "source": str(source)}
                )
                continue
            digest = fingerprint(case)
            if digest in existing_fingerprints or digest in seen:
                report["duplicates"].append(
                    {"id": case["id"], "source": str(source)}
                )
                continue
            seen.add(digest)
            report["new_cases"].append(case)

    if write and report["new_cases"]:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            yaml.safe_dump(
                {"cases": report["new_cases"]}, allow_unicode=True, sort_keys=False
            ),
            encoding="utf-8",
        )
        report["written_to"] = str(out)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="合并 Bad-case 候选（默认 dry-run）")
    parser.add_argument("sources", nargs="+", type=Path, help="候选文件（可多个）")
    parser.add_argument(
        "--into",
        type=Path,
        default=ROOT / "eval" / "cases" / "selection_decision_gates.yaml",
        help="现有用例集（用于去重比对）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "eval" / "failures" / "merged-cases.yaml",
        help="--write 时的输出路径",
    )
    parser.add_argument("--write", action="store_true", help="写入合并结果")
    args = parser.parse_args()

    report = merge_cases(
        args.sources, into=args.into, out=args.out, write=args.write
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not report["invalid"] else 1)


if __name__ == "__main__":
    main()
