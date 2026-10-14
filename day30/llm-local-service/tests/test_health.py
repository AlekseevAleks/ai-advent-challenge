"""Проверки liveness/readiness и таймаута health-check."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import OllamaHealth
from app.main import create_app


def test_health_live_is_available_without_ollama(settings: Settings) -> None:
    """Liveness не зависит от локальной модели."""
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "local-llm-service"


def test_health_reports_ollama_status(client: TestClient) -> None:
    """Readiness возвращает понятный статус модели."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ollama"] == "ok"
    assert body["model_available"] is True
    assert body["model"] == "test-model"


def test_health_returns_503_when_ollama_is_down(settings: Settings) -> None:
    """Недоступность Ollama не ломает процесс и не зависает."""
    app = create_app(settings)
    with TestClient(app) as client:
        app.state.llm.health = AsyncMock(
            return_value=OllamaHealth(
                status="unavailable",
                model_available=False,
                detail="Ollama не запущена.",
            )
        )
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["ollama"] == "unavailable"
    assert response.json()["model_available"] is False


def test_docs_are_available(client: TestClient) -> None:
    """OpenAPI документация FastAPI включена."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()
