"""三塔模型召回客户端：用户塔 + 查询塔。"""

import os
from typing import cast

import httpx


class TowerClient:
    def __init__(self) -> None:
        self.user_endpoint: str = os.environ["TOWER_USER_ENDPOINT"]
        self.query_endpoint: str = os.environ["TOWER_QUERY_ENDPOINT"]
        self.client: httpx.AsyncClient = httpx.AsyncClient(timeout=5.0)

    async def encode_user(self, user_id: str) -> list[float]:
        r = await self.client.post(self.user_endpoint, json={"user_id": user_id})
        _ = r.raise_for_status()
        return cast(list[float], r.json()["embedding"])

    async def encode_query(self, query: str) -> list[float]:
        r = await self.client.post(self.query_endpoint, json={"query": query})
        _ = r.raise_for_status()
        return cast(list[float], r.json()["embedding"])


tower_client = TowerClient()
