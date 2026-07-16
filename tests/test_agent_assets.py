"""Integration tests for the AgentAsset control-plane slice."""

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


def _project_scope(project_id: str = "demo") -> dict[str, str]:
    return {"level": "project", "project_id": project_id}


def _create_active_memory(client: TestClient, project_id: str = "demo") -> dict[str, object]:
    created = client.post(
        "/api/memories",
        json={
            "content": "demo project uses pnpm",
            "kind": "fact",
            "scope": _project_scope(project_id),
            "client_id": "web-ui",
        },
    )
    assert created.status_code == 200
    memory = created.json()
    approved = client.post(f"/api/memories/{memory['id']}/approve", json={})
    assert approved.status_code == 200
    return approved.json()


def _create_asset(client: TestClient, name: str = "Backend Maintainer") -> dict[str, object]:
    response = client.post(
        "/api/assets",
        json={
            "name": name,
            "description": "Owns backend maintenance",
            "role_tags": ["backend", "maintainer"],
            "default_sync_mode": "manual",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_asset_projects_endpoints_and_scope_visible_memories(client: TestClient) -> None:
    asset = _create_asset(client)
    asset_id = str(asset["id"])
    project = client.post(
        "/api/projects",
        json={"id": "demo", "name": "Demo"},
    )
    assert project.status_code == 200

    membership = client.post(
        f"/api/assets/{asset_id}/projects",
        json={"project_id": "demo", "role": "maintainer", "sync_mode": "manual"},
    )
    assert membership.status_code == 200

    endpoint = client.post(
        f"/api/assets/{asset_id}/endpoints",
        json={"client_id": "codex-local", "platform": "codex", "display_name": "Local Codex"},
    )
    assert endpoint.status_code == 200

    expected = _create_active_memory(client)
    detail = client.get(f"/api/assets/{asset_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["projects"][0]["project_id"] == "demo"
    assert payload["endpoints"][0]["client_id"] == "codex-local"
    assert payload["memory_count"] == 1
    assert payload["memories"][0]["id"] == expected["id"]


def test_manual_grant_shares_memory_without_copying_or_leaking_project_scope(client: TestClient) -> None:
    asset = _create_asset(client, "Reviewer")
    asset_id = str(asset["id"])
    isolated_memory = _create_active_memory(client, "private-project")

    before = client.get(f"/api/assets/{asset_id}/memories")
    assert before.status_code == 200
    assert before.json() == []

    grant = client.post(
        f"/api/assets/{asset_id}/grants",
        json={"memory_id": isolated_memory["id"], "sync_mode": "manual"},
    )
    assert grant.status_code == 200
    assert grant.json()["memory_id"] == isolated_memory["id"]

    visible = client.get(f"/api/assets/{asset_id}/memories")
    assert visible.status_code == 200
    assert [memory["id"] for memory in visible.json()] == [isolated_memory["id"]]

    # The grant references the canonical record; it never creates another memory projection.
    all_memories = client.get("/api/memories").json()
    assert [memory["id"] for memory in all_memories] == [isolated_memory["id"]]


def test_asset_rejects_duplicate_endpoint_client_id(client: TestClient) -> None:
    first = _create_asset(client, "Planner")
    second = _create_asset(client, "Researcher")
    endpoint = {"client_id": "shared-client", "platform": "claude"}

    assert client.post(f"/api/assets/{first['id']}/endpoints", json=endpoint).status_code == 200
    duplicate = client.post(f"/api/assets/{second['id']}/endpoints", json=endpoint)
    assert duplicate.status_code == 409
