"""Integration tests for endpoint setup/status HTTP APIs. Plan §3."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memory_workbench.api.deps import reset_for_tests
from memory_workbench.main import create_app


@pytest.fixture
def client() -> TestClient:
    reset_for_tests(":memory:")
    with TestClient(create_app()) as test_client:
        yield test_client


def _create_asset(client: TestClient) -> dict:
    response = client.post("/api/assets", json={"name": "Codex Local"})
    assert response.status_code == 200
    return response.json()


def _create_endpoint(client: TestClient, asset_id: str) -> dict:
    response = client.post(
        f"/api/assets/{asset_id}/endpoints",
        json={
            "client_id": "codex-local",
            "platform": "codex",
            "display_name": "Codex CLI",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_endpoint_status_never_seen_before_first_use(client: TestClient):
    asset = _create_asset(client)
    endpoint = _create_endpoint(client, asset["id"])

    response = client.get(
        f"/api/assets/{asset['id']}/endpoints/{endpoint['id']}/status"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "never_seen"
    assert body["last_seen_at"] is None
    assert body["last_operation"] is None
    assert body["visible_memory_count"] == 0


def test_endpoint_setup_installed_profile(client: TestClient):
    asset = _create_asset(client)
    endpoint = _create_endpoint(client, asset["id"])

    response = client.post(
        f"/api/assets/{asset['id']}/endpoints/{endpoint['id']}/setup",
        json={"profile": "installed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["client_id"] == "codex-local"
    assert body["profile"] == "installed"
    server = body["config"]["mcpServers"]["memory-workbench"]
    assert server["command"] == "memory-workbench-mcp"
    assert server["env"]["MW_CLIENT_ID"] == "codex-local"


def test_endpoint_setup_rejects_relative_repo_path(client: TestClient):
    asset = _create_asset(client)
    endpoint = _create_endpoint(client, asset["id"])

    response = client.post(
        f"/api/assets/{asset['id']}/endpoints/{endpoint['id']}/setup",
        json={"profile": "repository", "repository_path": "relative/path"},
    )
    assert response.status_code == 400


def test_endpoint_setup_rejects_cross_asset(client: TestClient):
    """An endpoint id from asset A cannot be queried via asset B."""
    asset_a = _create_asset(client)
    endpoint_a = _create_endpoint(client, asset_a["id"])

    asset_b = client.post("/api/assets", json={"name": "Other"}).json()

    response = client.get(
        f"/api/assets/{asset_b['id']}/endpoints/{endpoint_a['id']}/status"
    )
    assert response.status_code == 404


def test_asset_detail_includes_status_fields(client: TestClient):
    asset = _create_asset(client)
    _create_endpoint(client, asset["id"])

    response = client.get(f"/api/assets/{asset['id']}")
    assert response.status_code == 200
    endpoints = response.json()["endpoints"]
    assert len(endpoints) == 1
    assert endpoints[0]["status"] == "never_seen"
    assert "last_seen_at" in endpoints[0]
    assert "visible_memory_count" in endpoints[0]
