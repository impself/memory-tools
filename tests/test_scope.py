"""Table-driven scope visibility matrix tests.

Spec §6.3: scope filtering happens before full-text or vector ranking.
Project constraints must not leak across projects.

Visibility rule (MemoryScope.can_read):
- caller at broader level cannot see narrower stored records
- caller at narrower level can see broader-or-equal stored records if
  every id present in `stored` matches caller's id; None ids in stored
  match anything.
"""

from __future__ import annotations

import pytest

from memory_workbench.domain.models import MemoryScope, ScopeLevel


# (caller_level, caller_ids, stored_level, stored_ids, expected_visible)
CASES = [
    # Global caller sees only global
    ("global", {}, "global", {}, True),
    ("global", {}, "workspace", {"workspace_id": "w1"}, False),
    ("global", {}, "project", {"project_id": "p1"}, False),
    ("global", {}, "agent", {"agent_id": "a1"}, False),
    ("global", {}, "session", {"session_id": "s1"}, False),

    # Workspace caller: sees own workspace + global
    ("workspace", {"workspace_id": "w1"}, "global", {}, True),
    ("workspace", {"workspace_id": "w1"}, "workspace", {"workspace_id": "w1"}, True),
    ("workspace", {"workspace_id": "w1"}, "workspace", {"workspace_id": "w2"}, False),
    ("workspace", {"workspace_id": "w1"}, "project", {"project_id": "p1"}, False),
    ("workspace", {"workspace_id": "w1"}, "agent", {"agent_id": "a1"}, False),

    # Project caller: sees matching workspace + own project + global.
    # Caller MUST declare parent workspace_id to see workspace-level records
    # (strict no-leak rule).
    ("project", {"project_id": "p1"}, "global", {}, True),
    ("project", {"project_id": "p1"}, "workspace", {"workspace_id": "w1"}, False),
    ("project", {"project_id": "p1", "workspace_id": "w1"}, "workspace", {"workspace_id": "w1"}, True),
    ("project", {"project_id": "p1", "workspace_id": "w1"}, "workspace", {"workspace_id": "w2"}, False),
    ("project", {"project_id": "p1"}, "project", {"project_id": "p1"}, True),
    ("project", {"project_id": "p1"}, "project", {"project_id": "p2"}, False),
    ("project", {"project_id": "p1"}, "agent", {"agent_id": "a1"}, False),
    ("project", {"project_id": "p1"}, "session", {"session_id": "s1"}, False),

    # Agent caller: sees own agent record + matching project/workspace/global.
    # Parent ids must be declared; an agent without project_id cannot see
    # any project-level record (no way to know which project is in scope).
    ("agent", {"agent_id": "a1"}, "global", {}, True),
    ("agent", {"agent_id": "a1"}, "project", {"project_id": "p1"}, False),
    ("agent", {"agent_id": "a1", "project_id": "p1"}, "project", {"project_id": "p1"}, True),
    ("agent", {"agent_id": "a1", "project_id": "p1"}, "project", {"project_id": "p2"}, False),
    ("agent", {"agent_id": "a1"}, "agent", {"agent_id": "a1"}, True),
    ("agent", {"agent_id": "a1"}, "agent", {"agent_id": "a2"}, False),
    ("agent", {"agent_id": "a1"}, "session", {"session_id": "s1"}, False),

    # Session caller: sees everything down the lineage if ids match
    ("session", {"session_id": "s1"}, "global", {}, True),
    ("session", {"session_id": "s1"}, "session", {"session_id": "s1"}, True),
    ("session", {"session_id": "s1"}, "session", {"session_id": "s2"}, False),
    ("session", {"session_id": "s1", "agent_id": "a1"}, "session", {"session_id": "s1", "agent_id": "a1"}, True),
    ("session", {"session_id": "s1", "agent_id": "a1"}, "session", {"session_id": "s1", "agent_id": "a2"}, False),
]


def _make(level: str, ids: dict) -> MemoryScope:
    return MemoryScope(level=ScopeLevel(level), **ids)


@pytest.mark.parametrize("caller_level, caller_ids, stored_level, stored_ids, expected", CASES)
def test_scope_visibility_matrix(caller_level, caller_ids, stored_level, stored_ids, expected):
    caller = _make(caller_level, caller_ids)
    stored = _make(stored_level, stored_ids)
    assert caller.can_read(stored) is expected, (
        f"caller={caller_level}{caller_ids} stored={stored_level}{stored_ids} "
        f"expected={expected} got={not expected}"
    )


# --- id validation --------------------------------------------------------


@pytest.mark.parametrize("level,missing_field", [
    ("workspace", "workspace_id"),
    ("project", "project_id"),
    ("agent", "agent_id"),
    ("session", "session_id"),
])
def test_scope_requires_id(level, missing_field):
    """Each non-global level requires its corresponding id."""
    import pytest as _pytest
    with _pytest.raises(ValueError, match=missing_field):
        MemoryScope(level=ScopeLevel(level))


def test_scope_global_accepts_no_ids():
    s = MemoryScope(level=ScopeLevel.GLOBAL)
    assert s.workspace_id is None
    assert s.project_id is None


def test_scope_project_with_workspace_parent_ok():
    s = MemoryScope(
        level=ScopeLevel.PROJECT,
        workspace_id="w1",
        project_id="p1",
    )
    assert s.workspace_id == "w1"
    assert s.project_id == "p1"
