"""BGE-M3 embedding service used by Lector category retrieval."""

import asyncio
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, field_validator

VECTOR_DIM = 1024
DEFAULT_MODEL = "BAAI/bge-m3"


class Encoder(Protocol):
    model_name: str

    def encode(self, text: str) -> list[float]: ...


class SentenceTransformerEncoder:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, text: str) -> list[float]:
        vector = self._model.encode(text, normalize_embeddings=False)
        return [float(value) for value in vector.tolist()]


class QueryRequest(BaseModel):
    query: str

    @field_validator("query")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class UserRequest(BaseModel):
    user_id: str

    @field_validator("user_id")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_id must not be blank")
        return value


class EmbeddingResponse(BaseModel):
    embedding: list[float]


def _normalize(vector: list[float]) -> list[float]:
    if len(vector) != VECTOR_DIM:
        raise ValueError(f"expected {VECTOR_DIM} dimensions, received {len(vector)}")
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("embedding contains non-finite values")
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise ValueError("embedding has zero norm")
    return [value / norm for value in vector]


def create_app(encoder: Encoder | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if encoder is not None:
            app.state.encoder = encoder
        else:
            model_name = os.environ.get("TOWER_MODEL", DEFAULT_MODEL)
            app.state.encoder = await asyncio.to_thread(
                SentenceTransformerEncoder, model_name
            )
        yield

    api = FastAPI(title="Lector Query Tower", lifespan=lifespan)

    async def embed(request: Request, text: str) -> EmbeddingResponse:
        active: Encoder = request.app.state.encoder
        try:
            raw = await asyncio.to_thread(active.encode, text)
            return EmbeddingResponse(embedding=_normalize(raw))
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @api.get("/health")
    async def health(request: Request) -> dict[str, str | int]:
        active: Encoder = request.app.state.encoder
        return {
            "status": "ready",
            "model": active.model_name,
            "dimension": VECTOR_DIM,
        }

    @api.post("/encode/query", response_model=EmbeddingResponse)
    async def encode_query(payload: QueryRequest, request: Request) -> EmbeddingResponse:
        return await embed(request, payload.query)

    @api.post("/encode/user", response_model=EmbeddingResponse)
    async def encode_user(payload: UserRequest, request: Request) -> EmbeddingResponse:
        return await embed(request, f"user:{payload.user_id}")

    return api


app = create_app()
