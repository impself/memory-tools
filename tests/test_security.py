"""Security tests: scope visibility on correct, secret re-scan, lifecycle guards.

Spec §10:
- Secret detection at write
- No cross-scope modification
- Correct path must not bypass safety
"""

from __future__ import annotations

import pytest

from memory_workbench.api.deps import reset_for_tests, session_dep
from memory_workbench.domain import service
from memory_workbench.domain.errors import (
    InvalidTransition,
    MemoryNotFound,
    ScopeViolation,
    SecretContent,
)
from memory_workbench.domain.models import (
    CallerContext,
    MemoryKind,
    MemoryScope,
    ScopeLevel,
)


@pytest.fixture
def session():
    reset_for_tests(":memory:")
    sess = session_dep()
    yield sess
    sess.close()


def _ctx(client: str, project_id: str) -> CallerContext:
    return CallerContext(
        client_id=client,
        agent_id=f"{client}-agent",
        scope=MemoryScope(level=ScopeLevel.PROJECT, project_id=project_id),
    )


# --- propose: secret scan ------------------------------------------------


def test_propose_rejects_secret(session):
    with pytest.raises(SecretContent):
        service.propose(
            session, _ctx("client-a", "demo"),
            service.ProposeInput(
                content="OpenAI key: sk-abcdefghijklmnopqrstuvwxyz1234567890",
                kind=MemoryKind.FACT,
                scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            ),
        )


# --- correct: secret re-scan --------------------------------------------


def test_correct_rejects_secret_in_new_content(session):
    rec = service.propose(
        session, _ctx("client-a", "demo"),
        service.ProposeInput(
            content="harmless",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    with pytest.raises(SecretContent):
        service.correct(
            session, _ctx("client-a", "demo"),
            service.CorrectInput(
                memory_id=rec.id,
                content="now with key: ghp_" + "a" * 36,
            ),
        )


# --- correct: scope visibility ------------------------------------------


def test_correct_rejects_cross_scope(session):
    """Client B cannot correct a record in project A."""
    rec = service.propose(
        session, _ctx("client-a", "project-a"),
        service.ProposeInput(
            content="project-a fact",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="project-a"),
            auto_approve=True,
        ),
    )
    session.commit()
    with pytest.raises(ScopeViolation):
        service.correct(
            session, _ctx("client-b", "project-b"),
            service.CorrectInput(memory_id=rec.id, content="hijack attempt"),
        )


def test_correct_unknown_id_raises_not_found(session):
    with pytest.raises(MemoryNotFound):
        service.correct(
            session, _ctx("client-a", "demo"),
            service.CorrectInput(memory_id="mem_doesnotexist", content="x"),
        )


# --- lifecycle guards ----------------------------------------------------


def test_correct_revoked_raises_invalid_transition(session):
    rec = service.propose(
        session, _ctx("client-a", "demo"),
        service.ProposeInput(
            content="temporary",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    service.revoke(session, rec.id, actor_id="user")
    session.commit()
    with pytest.raises(InvalidTransition):
        service.correct(
            session, _ctx("client-a", "demo"),
            service.CorrectInput(memory_id=rec.id, content="after revoke"),
        )


def test_approve_only_candidate(session):
    rec = service.propose(
        session, _ctx("client-a", "demo"),
        service.ProposeInput(
            content="needs review",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=False,
        ),
    )
    session.commit()
    assert rec.state.value == "candidate"

    approved = service.approve(session, rec.id, actor_id="user")
    assert approved.state.value == "active"

    # Approving again must fail
    with pytest.raises(InvalidTransition):
        service.approve(session, rec.id, actor_id="user")


def test_revoke_idempotent_or_blocked(session):
    rec = service.propose(
        session, _ctx("client-a", "demo"),
        service.ProposeInput(
            content="to revoke",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    service.revoke(session, rec.id, actor_id="user")
    session.commit()
    with pytest.raises(InvalidTransition):
        service.revoke(session, rec.id, actor_id="user")


def test_purge_unknown_raises_not_found(session):
    with pytest.raises(MemoryNotFound):
        service.purge(session, "mem_nope", actor_id="user")


# --- search: no cross-project leak --------------------------------------


def test_search_does_not_leak_across_projects(session):
    service.propose(
        session, _ctx("client-a", "demo"),
        service.ProposeInput(
            content="demo-only",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    results, _ = service.search(
        session, _ctx("client-b", "other"),
        "demo-only",
    )
    session.commit()
    assert results == []
