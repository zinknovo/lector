import asyncio
import json
import os
from pathlib import Path

os.environ.setdefault("OPENSEARCH_HOST", "localhost")
os.environ.setdefault("OPENSEARCH_USER", "test")
os.environ.setdefault("OPENSEARCH_PASS", "test")
os.environ.setdefault("TOWER_USER_ENDPOINT", "http://localhost/user")
os.environ.setdefault("TOWER_QUERY_ENDPOINT", "http://localhost/query")

from app.tools.category_insight import INDEX_NAME as QUERY_INDEX_NAME
from app.tools.category_insight import SEARCH_PIPELINE_NAME
from scripts.build_category_kb import INDEX_MAPPING, VECTOR_DIM, build_category_kb
from scripts.build_category_kb import INDEX_NAME as BUILD_INDEX_NAME
from scripts.setup_pipeline import PIPELINE_NAME


class FakeIndices:
    created = None

    def exists(self, index: str) -> bool:
        return False

    def create(self, index: str, body: dict) -> None:
        self.created = (index, body)

    def refresh(self, index: str) -> None:
        self.refreshed = index


class FakeOpenSearch:
    def __init__(self) -> None:
        self.indices = FakeIndices()
        self.documents: list[tuple[str, str, dict]] = []

    def index(self, *, index: str, id: str, body: dict) -> None:
        self.documents.append((index, id, body))


def test_builder_validates_embeds_and_indexes_cards(tmp_path: Path) -> None:
    cards_path = tmp_path / "cards.jsonl"
    valid = {
        "card_id": "card-1",
        "category": "wireless earbuds",
        "card_type": "bestseller",
        "summary": "wireless earbuds: ANC / long battery",
        "raw_evidence": ["Model A | 299 | strong reviews"],
        "last_updated": "2026-07-14T00:00:00Z",
        "confidence": 0.9,
    }
    invalid = {**valid, "card_id": "card-2", "confidence": 0.1}
    cards_path.write_text(
        "\n".join(json.dumps(item) for item in (valid, invalid)),
        encoding="utf-8",
    )
    client = FakeOpenSearch()

    async def encode(text: str) -> list[float]:
        assert "wireless earbuds" in text
        return [0.0] * VECTOR_DIM

    result = asyncio.run(build_category_kb(cards_path, client, encode))

    assert result.read == 2
    assert result.indexed == 1
    assert result.rejected == 1
    assert client.documents[0][1] == "card-1"
    assert len(client.documents[0][2]["content_vector"]) == VECTOR_DIM


def test_builder_and_query_use_the_same_lector_resources() -> None:
    assert BUILD_INDEX_NAME == QUERY_INDEX_NAME == "lector_category_kb"
    assert PIPELINE_NAME == SEARCH_PIPELINE_NAME == "lector_hybrid_pipeline"


def test_index_mapping_only_uses_built_in_text_analyzer() -> None:
    properties = INDEX_MAPPING["mappings"]["properties"]
    assert properties["category"]["analyzer"] == "standard"
    assert properties["summary"]["analyzer"] == "standard"
    assert properties["raw_evidence"]["analyzer"] == "standard"
