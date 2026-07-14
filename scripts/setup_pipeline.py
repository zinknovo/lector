"""Register the Lector hybrid-search pipeline in OpenSearch."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from opensearchpy import OpenSearch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.recall.opensearch_config import opensearch_connection_settings

load_dotenv(ROOT / ".env")

PIPELINE_NAME = os.environ.get(
    "CATEGORY_KB_SEARCH_PIPELINE", "lector_hybrid_pipeline"
)

PIPELINE_BODY = {
    "description": "KNN + BM25 双路召回的归一与加权融合",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {"weights": [0.7, 0.3]},
                },
            }
        }
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the Lector hybrid-search pipeline in OpenSearch"
    )
    parser.parse_args()
    client = OpenSearch(**opensearch_connection_settings())
    resp = client.search_pipeline.put(id=PIPELINE_NAME, body=PIPELINE_BODY)
    print(f"Registered search pipeline: {PIPELINE_NAME}")
    print(resp)


if __name__ == "__main__":
    main()
