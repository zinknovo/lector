"""Load configurable cost tables for shipping and duty estimation.

Default values live in code; can be overridden via JSON file:
- env: `LECTOR_COST_TABLES_PATH=/path/to/cost_tables.json`
- default: `data/cost_tables.json` (repo-local)
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


class UnknownDestinationError(ValueError):
    """该目的地没有成本口径：明确失败，不套用其它市场的数字。"""

    def __init__(self, destination: str) -> None:
        super().__init__(f"没有 {destination} 的成本口径（成本表未配置该市场）")
        self.destination = destination


COST_TABLE_META_DEFAULT: dict[str, Any] = {
    "table_version": "v1.0",
    "updated_at": "2026-07-16",
    "calibration": {
        "US": "主路径（v1 默认口径）",
        "UK": "粗估（未细调）",
        "DE": "粗估（未细调）",
        "JP": "粗估（未细调）",
        "CN": "仅兼容（选品主路径不应使用）",
    },
}


def _default_cost_tables_path() -> Path:
    # app/recall/cost_tables.py -> app/recall -> app -> project root
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "cost_tables.json"


def _read_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return data


@lru_cache(maxsize=1)
def load_cost_tables() -> dict[str, Any]:
    path = os.environ.get("LECTOR_COST_TABLES_PATH")
    if path:
        p = Path(path)
    else:
        p = _default_cost_tables_path()

    if not p.exists():
        return {}

    try:
        return _read_json_file(p)
    except Exception:
        # Never hard-fail for MVP; fallback to code defaults.
        return {}


def load_cost_tables_meta() -> dict[str, Any]:
    """成本表版本 / 更新时间 / 各目的地校准状态（缺失时用代码默认）。"""
    data = load_cost_tables()
    raw = data.get("META")
    if not isinstance(raw, dict):
        return COST_TABLE_META_DEFAULT
    merged = dict(COST_TABLE_META_DEFAULT)
    merged.update({key: value for key, value in raw.items() if value})
    return merged


def destination_calibration(destination: str) -> str:
    """该目的地的校准状态文案（未知目的地也给出统一说明）。"""
    calibration = load_cost_tables_meta().get("calibration") or {}
    if isinstance(calibration, dict):
        value = calibration.get(destination.upper())
        if isinstance(value, str) and value:
            return value
    return "未标注校准状态"


def load_outbound_shipping_table(
    default_table: dict[str, list[tuple[float, float, int]]],
) -> dict[str, list[tuple[float, float, int]]]:
    """destination -> [(min_weight_kg, fee_cny, eta_days), ...]"""
    data = load_cost_tables()
    raw = data.get("OUTBOUND_SHIPPING_TABLE")
    if not isinstance(raw, dict):
        return default_table

    table: dict[str, list[tuple[float, float, int]]] = {}
    for dest, rows in raw.items():
        if not isinstance(dest, str) or not isinstance(rows, list):
            continue
        parsed_rows: list[tuple[float, float, int]] = []
        for row in rows:
            if (
                isinstance(row, list)
                and len(row) == 3
                and isinstance(row[0], (int, float))
                and isinstance(row[1], (int, float))
                and isinstance(row[2], int)
            ):
                parsed_rows.append((float(row[0]), float(row[1]), int(row[2])))
        if parsed_rows:
            table[dest.upper()] = parsed_rows

    return table or default_table


def load_duty_tables(
    default_by_destination: dict[str, tuple[float, Any]],
    default_by_platform: dict[str, tuple[float, Any]],
) -> tuple[dict[str, tuple[float, Any]], dict[str, tuple[float, Any]]]:
    data = load_cost_tables()
    by_dest_raw = data.get("DUTY_BY_DESTINATION")
    by_platform_raw = data.get("DUTY_TABLE")

    # Keep existing tiers as opaque values; duty.py uses Literal tiers.
    by_dest = default_by_destination
    by_platform = default_by_platform

    if isinstance(by_dest_raw, dict):
        new_by_dest: dict[str, tuple[float, Any]] = {}
        for dest, v in by_dest_raw.items():
            if not isinstance(dest, str) or not isinstance(v, list) or len(v) != 2:
                continue
            if isinstance(v[0], (int, float)) and isinstance(v[1], str):
                new_by_dest[dest.upper()] = (float(v[0]), v[1])
        if new_by_dest:
            by_dest = new_by_dest

    if isinstance(by_platform_raw, dict):
        new_by_platform: dict[str, tuple[float, Any]] = {}
        for platform, v in by_platform_raw.items():
            if not isinstance(platform, str) or not isinstance(v, list) or len(v) != 2:
                continue
            if isinstance(v[0], (int, float)) and isinstance(v[1], str):
                new_by_platform[platform.lower()] = (float(v[0]), v[1])
        if new_by_platform:
            by_platform = new_by_platform

    return by_dest, by_platform

