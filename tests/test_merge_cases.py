"""候选合并：指纹去重、完整性/结构校验、dry-run 与 --write 行为。"""

import yaml

from scripts.merge_cases import merge_cases


def _complete_case(case_id: str, product: str = "A1") -> dict:
    return {
        "id": case_id,
        "inputs": {"product_id": product, "overall_score": 0.8},
        "expected": {"recommendation": "watch"},
    }


def _write(path, cases) -> None:
    path.write_text(
        yaml.safe_dump({"cases": cases}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_deduplicates_by_fingerprint_across_sources(tmp_path) -> None:
    into = tmp_path / "cases.yaml"
    _write(into, [_complete_case("existing", product="Z9")])
    first = tmp_path / "f1.yaml"
    _write(first, [_complete_case("new-1", product="A1")])
    second = tmp_path / "f2.yaml"
    # 相同 inputs+expected（键顺序不同）→ 视为重复；另一条与现有用例集重复
    duplicate = {
        "id": "copy",
        "inputs": {"overall_score": 0.8, "product_id": "A1"},
        "expected": {"recommendation": "watch"},
    }
    _write(second, [duplicate, _complete_case("existing", product="Z9")])

    report = merge_cases([first, second], into=into, out=tmp_path / "out.yaml")

    assert [case["id"] for case in report["new_cases"]] == ["new-1"]
    duplicate_ids = {entry["id"] for entry in report["duplicates"]}
    assert duplicate_ids == {"copy", "existing"}


def test_incomplete_and_invalid_entries_are_reported(tmp_path) -> None:
    into = tmp_path / "cases.yaml"
    _write(into, [])
    source = tmp_path / "candidates.yaml"
    yaml.safe_dump(
        {
            "candidate_cases": [
                {"id": "no-expected", "inputs": {"a": 1}, "expected": {}},
                {"id": "bad-reco", "inputs": {"a": 1}, "expected": {"recommendation": "maybe"}},
                {"id": "no-inputs", "expected": {"recommendation": "watch"}},
            ]
        },
        (source).open("w", encoding="utf-8"),
        allow_unicode=True,
    )

    report = merge_cases([source], into=into, out=tmp_path / "out.yaml")

    assert [entry["id"] for entry in report["incomplete"]] == ["no-expected"]
    assert len(report["invalid"]) == 2
    assert report["new_cases"] == []


def test_dry_run_does_not_write_and_write_only_emits_new(tmp_path) -> None:
    into = tmp_path / "cases.yaml"
    _write(into, [])
    source = tmp_path / "f.yaml"
    _write(source, [_complete_case("new-1")])
    out = tmp_path / "merged.yaml"

    merge_cases([source], into=into, out=out)
    assert not out.exists()

    report = merge_cases([source], into=into, out=out, write=True)
    assert report["written_to"] == str(out)
    written = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert [case["id"] for case in written["cases"]] == ["new-1"]


def test_recall_failures_file_is_reported_as_unsupported(tmp_path) -> None:
    into = tmp_path / "cases.yaml"
    _write(into, [])
    source = tmp_path / "recall-failures.yaml"
    source.write_text(
        yaml.safe_dump({"queries": [{"id": "q1"}]}, allow_unicode=True),
        encoding="utf-8",
    )

    report = merge_cases([source], into=into, out=tmp_path / "out.yaml")

    assert report["new_cases"] == []
    assert any("召回失败查询" in note for note in report["notes"])
