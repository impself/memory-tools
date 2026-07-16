"""HTTP integration tests for the local admin interface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memory_workbench.api.deps import reset_for_tests
from memory_workbench.main import create_app


@pytest.fixture
def client():
    reset_for_tests(":memory:")
    with TestClient(create_app()) as test_client:
        yield test_client


def _project_scope(project_id: str = "demo") -> dict[str, str]:
    return {"level": "project", "project_id": project_id}


def _create_active_memory(client: TestClient, content: str = "project uses pnpm") -> dict:
    response = client.post(
        "/api/memories",
        json={
            "content": content,
            "kind": "fact",
            "scope": _project_scope(),
            "client_id": "web-ui",
        },
    )
    assert response.status_code == 200
    memory = response.json()
    approval = client.post(f"/api/memories/{memory['id']}/approve", json={})
    assert approval.status_code == 200
    return approval.json()


def test_http_proposal_rejects_auto_approval_request(client: TestClient) -> None:
    response = client.post(
        "/api/memories",
        json={
            "content": "project uses pnpm",
            "kind": "fact",
            "scope": _project_scope(),
            "client_id": "web-ui",
            "auto_approve": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_lifecycle_request_rejects_spoofed_actor(client: TestClient) -> None:
    response = client.post(
        "/api/memories",
        json={
            "content": "project uses pnpm",
            "kind": "fact",
            "scope": _project_scope(),
            "client_id": "web-ui",
        },
    )
    memory_id = response.json()["id"]

    approval = client.post(
        f"/api/memories/{memory_id}/approve",
        json={"actor_id": "forged-user"},
    )

    assert approval.status_code == 422
    assert approval.json()["detail"][0]["type"] == "extra_forbidden"


def test_http_search_persists_retrieval_trace(client: TestClient) -> None:
    memory = _create_active_memory(client)

    response = client.post(
        "/api/memories/search",
        json={
            "query": "pnpm",
            "scope": _project_scope(),
            "client_id": "web-ui",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["record"]["id"] == memory["id"]
    traces = client.get("/api/traces").json()
    assert len(traces) == 1
    assert traces[0]["id"] == response.json()["trace_id"]


def test_retrieval_trace_does_not_store_raw_query(client: TestClient) -> None:
    _create_active_memory(client, content="contact jane@example.com")
    raw_query = "jane@example.com"

    response = client.post(
        "/api/memories/search",
        json={
            "query": raw_query,
            "scope": _project_scope(),
            "client_id": "web-ui",
        },
    )

    assert response.status_code == 200
    stored_query = client.get("/api/traces").json()[0]["query"]
    assert raw_query not in stored_query
    assert stored_query.startswith("[redacted")


def test_explain_accepts_complete_project_scope(client: TestClient) -> None:
    memory = _create_active_memory(client)

    response = client.get(
        f"/api/memories/{memory['id']}/explain",
        params={
            "client_id": "web-ui",
            "level": "project",
            "project_id": "demo",
        },
    )

    assert response.status_code == 200
    assert response.json()["record"]["id"] == memory["id"]


def test_admin_ui_uses_compiled_react_bundle_without_inline_handlers(
    client: TestClient,
) -> None:
    html = client.get("/").text

    assert "onclick=" not in html
    assert '<div id="root"></div>' in html
    assert "/static/assets/index-" in html
