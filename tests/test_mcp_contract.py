"""Public MCP tool contract tests."""

from __future__ import annotations

import inspect
import json
import os

import pytest

from memory_workbench.api.deps import reset_for_tests
from memory_workbench.mcp.server import memory_propose, memory_search


def test_agent_proposal_cannot_request_approval() -> None:
    assert "auto_approve" not in inspect.signature(memory_propose).parameters

    reset_for_tests(":memory:")
    result = json.loads(
        memory_propose(
            content="project uses pnpm",
            kind="fact",
            level="project",
            client_id="codex",
            project_id="demo",
        )
    )

    assert result["state"] == "candidate"


def test_agent_search_cannot_include_inactive_memories() -> None:
    assert "include_inactive" not in inspect.signature(memory_search).parameters


@pytest.fixture
def clean_db():
    reset_for_tests(":memory:")


@pytest.fixture
def env_client_id(monkeypatch):
    """Set MW_CLIENT_ID=codex-local for the duration of one test."""
    monkeypatch.setenv("MW_CLIENT_ID", "codex-local")
    yield "codex-local"
    monkeypatch.delenv("MW_CLIENT_ID", raising=False)


def test_env_client_id_wins_over_argument(clean_db, env_client_id) -> None:
    """With MW_CLIENT_ID set, argument with same value is fine; mismatch is rejected."""
    result = json.loads(
        memory_propose(
            content="ok content",
            kind="fact",
            level="project",
            client_id=env_client_id,
            project_id="demo",
        )
    )
    assert result["state"] == "candidate"


def test_env_client_id_rejects_mismatching_argument(clean_db, env_client_id) -> None:
    """With MW_CLIENT_ID=codex-local, a tool call claiming claude-local is rejected."""
    result = json.loads(
        memory_propose(
            content="attempted spoof",
            kind="fact",
            level="project",
            client_id="claude-local",
            project_id="demo",
        )
    )
    assert "error" in result
    assert result["error"]["code"] == "VALIDATION"


def test_missing_client_id_falls_back_to_anonymous(clean_db, monkeypatch) -> None:
    """Unbound callers continue to work with scope-only behaviour."""
    monkeypatch.delenv("MW_CLIENT_ID", raising=False)
    result = json.loads(
        memory_propose(
            content="unbound caller",
            kind="fact",
            level="project",
            project_id="demo",
        )
    )
    assert result["state"] == "candidate"
