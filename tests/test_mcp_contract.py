"""Public MCP tool contract tests."""

from __future__ import annotations

import inspect
import json

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
