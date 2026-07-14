"""注册 globex_hybrid_pipeline 到 OpenSearch。"""

import os

from opensearchpy import OpenSearch

PIPELINE_NAME = "globex_hybrid_pipeline"

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
    client = OpenSearch(
        hosts=[{"host": os.environ["OPENSEARCH_HOST"], "port": 9200}],
        http_auth=(os.environ["OPENSEARCH_USER"], os.environ["OPENSEARCH_PASS"]),
        use_ssl=False,
    )
    resp = client.search_pipeline.put(id=PIPELINE_NAME, body=PIPELINE_BODY)
    print(f"Registered search pipeline: {PIPELINE_NAME}")
    print(resp)


if __name__ == "__main__":
    main()
