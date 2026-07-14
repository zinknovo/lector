#!/usr/bin/env bash
# 一次性注册 Lector hybrid pipeline 到 OpenSearch（开发期执行）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${OPENSEARCH_HOST:?OPENSEARCH_HOST is required}"
: "${OPENSEARCH_USER:?OPENSEARCH_USER is required}"
: "${OPENSEARCH_PASS:?OPENSEARCH_PASS is required}"

PIPELINE_NAME="${CATEGORY_KB_SEARCH_PIPELINE:-lector_hybrid_pipeline}"

curl -sS -X PUT "http://${OPENSEARCH_HOST}:9200/_search/pipeline/${PIPELINE_NAME}" \
  -u "${OPENSEARCH_USER}:${OPENSEARCH_PASS}" \
  -H "Content-Type: application/json" \
  -d '{
  "description": "KNN + BM25 双路召回的归一与加权融合",
  "phase_results_processors": [
    {
      "normalization-processor": {
        "normalization": { "technique": "min_max" },
        "combination": {
          "technique": "arithmetic_mean",
          "parameters": { "weights": [0.7, 0.3] }
        }
      }
    }
  ]
}'

echo
echo "Registered search pipeline: ${PIPELINE_NAME}"
