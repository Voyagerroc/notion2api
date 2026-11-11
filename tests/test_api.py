import pytest
from fastapi.testclient import TestClient

from app.config import API_KEY
from app.server import app


@pytest.fixture(scope="module")
def client():
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    with TestClient(app, headers=headers) as test_client:
        yield test_client


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "uptime" in data


def test_list_models(client):
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0
    model_ids = [m["id"] for m in data["data"]]
    assert "claude-sonnet4.6" in model_ids or "auto" in model_ids


def test_chat_completions_validation_error(client):
    # Missing required 'messages' field
    response = client.post("/v1/chat/completions", json={"model": "auto"})
    assert response.status_code == 422
