"""构建品类知识库并写入 OpenSearch 索引。"""

import json
import os
from pathlib import Path

import httpx
from opensearchpy import OpenSearch

CARDS_PATH = Path("data/category_cards.jsonl")
INDEX_NAME = "globex_category_kb"
VECTOR_DIM = 1024  # 与 Query 塔输出维度一致

client = OpenSearch(
    hosts=[{"host": os.environ["OPENSEARCH_HOST"], "port": 9200}],
    http_auth=(os.environ["OPENSEARCH_USER"], os.environ["OPENSEARCH_PASS"]),
    use_ssl=False,
)

# 同一份索引同时存：结构化字段 + 全文字段（ik 分词）+ KNN 向量字段
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
                    "engine": "faiss",  # 底层 ANN 引擎
                    "space_type": "cosinesimil",  # 与 Query 塔 cosine 一致
                },
            },
        },
    },
}


def main() -> None:
    """TODO: implement category KB indexing pipeline."""
    raise NotImplementedError("Category KB build pipeline is not implemented yet.")


if __name__ == "__main__":
    main()
