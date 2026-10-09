"""采购价命中率评测（教程 13-2 的口径，数据为人工金标）。

- 金标：`eval/procurement_gold.yaml`（品类 → 合理采购价区间 + 可接受来源）；
- 命中：返回价格落在区间内且 `source ∈ acceptable_sources`；
- 输出：命中率、来源分布（提取 / 估算 / 不可用）、未命中明细；
- 门禁：命中率低于 `--min-hit-rate` 时非零退出。

需要真实搜索 / 模型调用（费用与外部依赖），因此不进 pytest；
空金标会以退出码 2 明确提示"先补样本"，不算通过。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from app.tools.procurement_quote import procurement_quote

VALID_SOURCES = {"web_search", "retail_ratio_estimate", "unavailable"}
DEFAULT_GOLD = ROOT / "eval" / "procurement_gold.yaml"

InvokeFn = Callable[[str], Awaitable[Any]]


def validate_gold(samples: list[dict[str, Any]]) -> list[str]:
    """结构自检；返回问题列表（空列表=通过）。"""
    problems: list[str] = []
    for index, sample in enumerate(samples):
        label = f"样本 {index + 1}（{sample.get('category', '缺品类')}）"
        category = sample.get("category")
        if not isinstance(category, str) or not category.strip():
            problems.append(f"{label}: category 不能为空")
        price_min = sample.get("price_min")
        price_max = sample.get("price_max")
        if not isinstance(price_min, (int, float)) or not isinstance(
            price_max, (int, float)
        ):
            problems.append(f"{label}: price_min / price_max 必须是数字")
        elif price_min > price_max:
            problems.append(f"{label}: price_min 不能大于 price_max")
        sources = sample.get("acceptable_sources")
        if not isinstance(sources, list) or not sources:
            problems.append(f"{label}: acceptable_sources 不能为空")
        else:
            unknown = {
                source for source in sources if source not in VALID_SOURCES
            }
            if unknown:
                problems.append(f"{label}: 未知来源 {sorted(unknown)}")
    return problems


async def _default_invoke(category: str) -> Any:
    return await procurement_quote.ainvoke({"product_query": category})


async def run_gold(
    samples: list[dict[str, Any]], invoke: InvokeFn | None = None
) -> dict[str, Any]:
    """逐条跑金标并统计命中情况。"""
    call = invoke or _default_invoke
    rows: list[dict[str, Any]] = []
    for sample in samples:
        result = await call(str(sample["category"]))
        price = getattr(result, "procurement_cost_cny", None)
        source = str(getattr(result, "source", "unavailable"))
        price_min = float(sample["price_min"])
        price_max = float(sample["price_max"])
        accepted = {str(item) for item in sample["acceptable_sources"]}
        hit = (
            price is not None
            and price_min <= float(price) <= price_max
            and source in accepted
        )
        rows.append(
            {
                "category": sample["category"],
                "price": price,
                "source": source,
                "expect": [price_min, price_max],
                "acceptable_sources": sorted(accepted),
                "hit": hit,
            }
        )

    hits = [row for row in rows if row["hit"]]
    distribution: dict[str, int] = {}
    for row in rows:
        distribution[row["source"]] = distribution.get(row["source"], 0) + 1
    return {
        "samples": len(rows),
        "hits": len(hits),
        "hit_rate": (len(hits) / len(rows)) if rows else 0.0,
        "source_distribution": distribution,
        "misses": [row for row in rows if not row["hit"]],
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="采购价命中率评测（真实调用）")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument(
        "--min-hit-rate",
        type=float,
        default=0.6,
        help="命中率门禁（低于该值非零退出）",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    data = yaml.safe_load(args.gold.read_text(encoding="utf-8")) or {}
    samples = data.get("samples") or []
    if not samples:
        print(
            json.dumps(
                {"error": "金标为空：请先在 eval/procurement_gold.yaml 补入真实样本"},
                ensure_ascii=False,
            )
        )
        raise SystemExit(2)

    problems = validate_gold(samples)
    if problems:
        print(json.dumps({"invalid_gold": problems}, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    report = asyncio.run(run_gold(samples))
    report["gate"] = {
        "min_hit_rate": args.min_hit_rate,
        "passed": report["hit_rate"] >= args.min_hit_rate,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["gate"]["passed"] else 1)


if __name__ == "__main__":
    main()
