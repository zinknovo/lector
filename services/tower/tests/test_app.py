import math

from fastapi.testclient import TestClient

from services.tower.app import VECTOR_DIM, create_app


class FakeEncoder:
    model_name = "fake-bge-m3"

    def encode(self, text: str) -> list[float]:
        assert text.strip()
        return [1.0] * VECTOR_DIM


def test_query_endpoint_returns_normalized_1024_vector() -> None:
    with TestClient(create_app(FakeEncoder())) as client:
        response = client.post("/encode/query", json={"query": "wireless earbuds"})

    assert response.status_code == 200
    vector = response.json()["embedding"]
    assert len(vector) == 1024
    assert math.isclose(sum(value * value for value in vector), 1.0)


def test_user_endpoint_and_health() -> None:
    with TestClient(create_app(FakeEncoder())) as client:
        user = client.post("/encode/user", json={"user_id": "user-1"})
        health = client.get("/health")

    assert user.status_code == 200
    assert len(user.json()["embedding"]) == 1024
    assert health.json() == {
        "status": "ready",
        "model": "fake-bge-m3",
        "dimension": 1024,
    }


def test_empty_input_is_rejected() -> None:
    with TestClient(create_app(FakeEncoder())) as client:
        response = client.post("/encode/query", json={"query": "   "})

    assert response.status_code == 422
