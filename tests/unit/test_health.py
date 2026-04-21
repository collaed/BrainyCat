"""Unit tests for the health endpoint and config."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from brainycat.config import Settings
from brainycat.web import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_config_defaults() -> None:
    """Settings loads with sensible defaults."""
    s = Settings()
    assert s.database_url.startswith("postgresql://")
    assert s.data_dir == "/data/books"
    assert s.embedding_dim == 384
    assert s.session_max_age == 86400 * 7


def test_health_endpoint_db_connected(client: TestClient) -> None:
    """Health endpoint returns ok when DB is reachable."""
    mock_status = {
        "connected": True,
        "version": "16.13",
        "pgvector": True,
        "pg_trgm": True,
    }
    with patch("brainycat.web.db.health_check", new_callable=AsyncMock, return_value=mock_status):
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"]["connected"] is True
    assert data["db"]["pgvector"] is True


def test_health_endpoint_db_down(client: TestClient) -> None:
    """Health endpoint returns degraded when DB is unreachable."""
    mock_status = {"connected": False, "error": "connection refused"}
    with patch("brainycat.web.db.health_check", new_callable=AsyncMock, return_value=mock_status):
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["db"]["connected"] is False
