"""FAISS ANN 检索客户端：加载索引与元数据，按平台过滤召回。"""

import os
from pathlib import Path
from typing import Any, cast

import faiss
import numpy as np
from numpy.typing import NDArray


class AnnClient:
    def __init__(self, index_path: Path) -> None:
        self._index: faiss.Index = faiss.read_index(str(index_path))
        self._meta: dict[int, dict[str, Any]] = self._load_meta(
            index_path.with_suffix(".meta.json")
        )

    def _load_meta(self, path: Path) -> dict[int, dict[str, Any]]:
        import json

        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("meta file must contain a JSON object")
        return {int(k): v for k, v in raw.items() if isinstance(v, dict)}

    def search(self, emb: list[float], top_k: int, platform: str) -> list[dict[str, Any]]:
        vec: NDArray[np.float32] = np.asarray([emb], dtype=np.float32)
        scores, idxs = cast(
            tuple[NDArray[np.float32], NDArray[np.int64]],
            self._index.search(vec, top_k * 3),
        )  # 多召回点用于平台过滤

        results: list[dict[str, Any]] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0:
                continue
            meta = self._meta.get(int(idx))
            if meta and meta.get("platform") == platform:
                meta_copy = dict(meta)
                meta_copy["score"] = float(score)
                results.append(meta_copy)
            if len(results) >= top_k:
                break
        return results


class LazyAnnClient:
    """Delay FAISS loading until the first real recall request."""

    def __init__(self) -> None:
        self._client: AnnClient | None = None

    def _get_client(self) -> AnnClient:
        if self._client is None:
            self._client = AnnClient(Path(os.environ["ANN_INDEX_PATH"]))
        return self._client

    def search(
        self, emb: list[float], top_k: int, platform: str
    ) -> list[dict[str, Any]]:
        return self._get_client().search(emb, top_k, platform)


ann_client = LazyAnnClient()
