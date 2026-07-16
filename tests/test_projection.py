"""Projection replay equivalence tests.

Spec §10 invariant: drop projection, replay events, all non-purged records
restored to identical state.

Covers full lifecycle: candidate → approved → corrected (superseded) →
quarantined / revoked / purged.
"""

from __future__ import annotations

import pytest

from memory_workbench.api.deps import reset_for_tests, session_dep
from memory_workbench.domain import service
from memory_workbench.domain.models import (
    ActorType,
    CallerContext,
    MemoryKind,
    MemoryScope,
    MemoryState,
    ScopeLevel,
)
from memory_workbench.storage import repository as repo


@pytest.fixture
def session():
    reset_for_tests(":memory:")
    sess = session_dep()
    yield sess
    sess.close()


def _ctx(actor: str = "user", project_id: str | None = "demo") -> CallerContext:
    return CallerContext(
        client_id=actor,
        agent_id=f"{actor}-agent",
        scope=MemoryScope(level=ScopeLevel.PROJECT, project_id=project_id),
    )


def _snapshot(sess) -> dict[str, dict]:
    """Map: memory_id -> fields we care about."""
    out = {}
    for rec in repo.list_records(sess, limit=500):
        out[rec.id] = {
            "content": rec.content,
            "kind": rec.kind.value,
            "subject": rec.subject,
            "predicate": rec.predicate,
            "value": rec.value,
            "state": rec.state.value,
            "scope": rec.scope.model_dump(mode="json"),
            "supersedes_id": rec.supersedes_id,
        }
    return out


def test_replay_after_auto_approve_keeps_active(session):
    """P0: auto-approved memory must rebuild as ACTIVE, not CANDIDATE."""
    rec = service.propose(
        session, _ctx(),
        service.ProposeInput(
            content="project uses pnpm",
            kind=MemoryKind.PREFERENCE,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    assert rec.state == MemoryState.ACTIVE

    before = _snapshot(session)
    # Wipe projection
    session.query(repo.MemoryRow).delete()  # type: ignore[attr-defined]
    session.commit()

    repo.rebuild_projection(session)
    session.commit()

    after = _snapshot(session)
    assert rec.id in after, "auto-approved memory lost after replay"
    assert after[rec.id]["state"] == MemoryState.ACTIVE.value, (
        "auto-approved memory rebuilt as non-active — replay diverges from online state"
    )
    assert after[rec.id]["content"] == before[rec.id]["content"]


def test_replay_preserves_supersession_chain(session):
    """Corrected memory: old superseded, new active. Rebuild must preserve both."""
    old = service.propose(
        session, _ctx(),
        service.ProposeInput(
            content="use npm",
            kind=MemoryKind.PREFERENCE,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            subject="project:demo",
            predicate="package-manager",
            value="npm",
            auto_approve=True,
        ),
    )
    session.commit()
    new = service.correct(
        session, _ctx(),
        service.CorrectInput(memory_id=old.id, content="use pnpm instead", value="pnpm"),
    )
    session.commit()

    before = _snapshot(session)
    session.query(repo.MemoryRow).delete()  # type: ignore[attr-defined]
    session.commit()
    repo.rebuild_projection(session)
    session.commit()
    after = _snapshot(session)

    assert after[old.id]["state"] == MemoryState.SUPERSEDED.value
    assert after[new.id]["state"] == MemoryState.ACTIVE.value
    assert after[new.id]["supersedes_id"] == old.id
    assert after[new.id]["value"] == "pnpm"


def test_replay_after_revoke(session):
    rec = service.propose(
        session, _ctx(),
        service.ProposeInput(
            content="temp note",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    service.revoke(session, rec.id, actor_id="user")
    session.commit()

    session.query(repo.MemoryRow).delete()  # type: ignore[attr-defined]
    session.commit()
    repo.rebuild_projection(session)
    session.commit()

    recs = repo.list_records(session, limit=500)
    states = {r.id: r.state for r in recs}
    assert states[rec.id] == MemoryState.REVOKED


def test_purge_removes_content_and_projection(session):
    """Spec §10: purge removes content + projection; tombstone prevents resurrection."""
    rec = service.propose(
        session, _ctx(),
        service.ProposeInput(
            content="my secret api key value",
            kind=MemoryKind.FACT,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    service.purge(session, rec.id, actor_id="user")
    session.commit()

    # Projection gone
    assert repo.get_record(session, rec.id) is None

    # Rebuild must NOT resurrect
    repo.rebuild_projection(session)
    session.commit()
    assert repo.get_record(session, rec.id) is None

    # Event ledger still references it (tombstone), but no content anywhere
    events = repo.list_events(session, rec.id)
    assert any(e.event_type.value == "memory.purged" for e in events)
    for ev in events:
        assert "my secret api key value" not in str(ev.payload), (
            "purge leaked content into event payload"
        )


def test_replay_handles_quarantined(session):
    rec = service.propose(
        session, _ctx(),
        service.ProposeInput(
            content="needs review",
            kind=MemoryKind.EXPERIENCE,
            scope=MemoryScope(level=ScopeLevel.PROJECT, project_id="demo"),
            auto_approve=True,
        ),
    )
    session.commit()
    service.quarantine(session, rec.id, actor_id="user", reason="suspicious")
    session.commit()

    session.query(repo.MemoryRow).delete()  # type: ignore[attr-defined]
    session.commit()
    repo.rebuild_projection(session)
    session.commit()

    recs = repo.list_records(session, limit=500)
    assert recs[0].state == MemoryState.QUARANTINED
