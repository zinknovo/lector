"""Validate, embed and index category knowledge cards in OpenSearch."""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from opensearchpy import OpenSearch
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.recall.category_kb import CategoryCard
from app.recall.opensearch_config import opensearch_connection_settings
from scripts.etl.admit import admit

load_dotenv(ROOT / ".env")

CARDS_PATH = ROOT / "data/category_cards.jsonl"
INDEX_NAME = os.environ.get("CATEGORY_KB_INDEX", "lector_category_kb")
VECTOR_DIM = 1024

INDEX_MAPPING = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "properties": {
            "card_id": {"type": "keyword"},
            "category": {"type": "text", "analyzer": "ik_max_word"},
            "card_type": {"type": "keyword"},
            "summary": {"type": "text", "analyzer": "ik_max_word"},
            "raw_evidence": {"type": "text", "analyzer": "ik_max_word"},
            "last_updated": {"type": "date"},
            "confidence": {"type": "float"},
            "content_vector": {
                "type": "knn_vector",
                "dimension": VECTOR_DIM,
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "space_type": "cosinesimil",
                },
            },
        }
    },
}


class BuildCategoryKbResult(BaseModel):
    read: int = 0
    indexed: int = 0
    rejected: int = 0


async def build_category_kb(
    cards_path: Path,
    client: Any,
    encode: Callable[[str], Awaitable[list[float]]],
) -> BuildCategoryKbResult:
    """Build the index from a JSONL file and return deterministic counters."""
    if not cards_path.is_file():
        raise FileNotFoundError(f"Category card file not found: {cards_path}")
    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)

    result = BuildCategoryKbResult()
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
            vector = await encode(f"{card.category}\n{card.summary}")
            if len(vector) != VECTOR_DIM:
                raise ValueError(
                    f"Embedding dimension {len(vector)} does not match {VECTOR_DIM}"
                )
            document = card.model_dump(mode="json")
            document["content_vector"] = vector
            client.index(index=INDEX_NAME, id=card.card_id, body=document)
            result.indexed += 1
    client.indices.refresh(index=INDEX_NAME)
    return result


def _get_client() -> OpenSearch:
    return OpenSearch(**opensearch_connection_settings())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Lector category knowledge index"
    )
    parser.add_argument("--cards-path", type=Path, default=CARDS_PATH)
    args = parser.parse_args()
    from app.recall.towers import tower_client

    result = asyncio.run(
        build_category_kb(args.cards_path, _get_client(), tower_client.encode_query)
    )
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
