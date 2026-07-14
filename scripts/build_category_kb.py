"""Validate and import category knowledge cards into MongoDB."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.recall.category_kb import CategoryCard
from app.recall.category_norm import normalize_category
from app.recall.category_store import (
    CategoryKnowledgeStore,
    MongoCategoryKnowledgeStore,
)
from scripts.etl.admit import admit

load_dotenv(ROOT / ".env")

CARDS_PATH = ROOT / "data/category_cards.jsonl"


class BuildCategoryKbResult(BaseModel):
    read: int = 0
    written: int = 0
    rejected: int = 0


async def build_category_kb(
    cards_path: Path,
    store: CategoryKnowledgeStore,
) -> BuildCategoryKbResult:
    """Validate a JSONL file and upsert all accepted cards in one batch."""
    if not cards_path.is_file():
        raise FileNotFoundError(f"Category card file not found: {cards_path}")

    result = BuildCategoryKbResult()
    accepted_cards: list[CategoryCard] = []
    with cards_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            result.read += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                result.rejected += 1
                continue
            if not isinstance(raw, dict):
                result.rejected += 1
                continue
            accepted, _reason = admit(raw)
            if not accepted:
                result.rejected += 1
                continue
            card = CategoryCard.model_validate(raw)
            accepted_cards.append(
                card.model_copy(
                    update={"category": normalize_category(card.category)}
                )
            )

    result.written = await store.upsert_many(accepted_cards)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Lector category knowledge cards into MongoDB"
    )
    parser.add_argument("--cards-path", type=Path, default=CARDS_PATH)
    args = parser.parse_args()
    result = asyncio.run(
        build_category_kb(args.cards_path, MongoCategoryKnowledgeStore())
    )
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
