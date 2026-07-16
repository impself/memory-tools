"""Tracer-bullet end-to-end test — spec §17.

Verifies the full chain:
  propose → SQLite event + projection → search (Trace written)
  → correct (supersede) → re-search reads new value, old excluded

Plus rebuildability: drop projection, replay events, get same state.
"""

from __future__ import annotations

import pytest

from memory_workbench.api.deps import reset_for_tests
from memory_workbench.domain import service
from memory_workbench.domain.models import (
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
    from memory_workbench.api.deps import session_dep
    sess = session_dep()
    yield sess
    sess.close()


def _ctx(client_id: str, project_id: str | None = None) -> CallerContext:
    return CallerContext(
        client_id=client_id,
        agent_id=f"{client_id}-agent",
        scope=MemoryScope(level=ScopeLevel.PROJECT, project_id=project_id),
    )


def test_tracer_bullet_chain(session):
    # --- 1. Client A proposes project memory ---
    ctx_a = _ctx("client-a", project_id="demo")
    rec = service.propose(
        session,
        ctx_a,
        service.ProposeInput(
            content="Demo project uses pnpm as package manager",
            kind=MemoryKind.PREFERENCE,
            scope=ctx_a.scope,
            subject="project:demo",
            predicate="package-manager",
            value="pnpm",
            auto_approve=True,
        ),
    )
    session.commit()

    assert rec.state == MemoryState.ACTIVE
    assert rec.id.startswith("mem_")

    # Event logged
    events = repo.list_events(session, rec.id)
    assert len(events) == 1
    assert events[0].event_type.value == "memory.proposed"

    # Projection visible
    fetched = repo.get_record(session, rec.id)
    assert fetched is not None
    assert fetched.content == "Demo project uses pnpm as package manager"

    # --- 2. Client B searches same project scope ---
    ctx_b = _ctx("client-b", project_id="demo")
    results, trace = service.search(session, ctx_b, "package-manager", limit=10)
    session.commit()

    assert len(results) == 1
    assert results[0].record.id == rec.id
    assert "subject match" in results[0].hit_reason or "predicate match" in results[0].hit_reason

    # Trace written
    assert trace.id.startswith("tr_")
    assert rec.id in trace.returned_ids

    # --- 3. Different project cannot see it ---
    ctx_other = _ctx("client-b", project_id="other-project")
    results_other, _ = service.search(session, ctx_other, "package-manager", limit=10)
    session.commit()
    assert len(results_other) == 0, "scope leak across projects"

    # --- 4. User corrects the memory ---
    corrected = service.correct(
        session,
        ctx_a,
        service.CorrectInput(
            memory_id=rec.id,
            content="Demo project uses bun as package manager (switched)",
            value="bun",
        ),
    )
    session.commit()

    assert corrected.id != rec.id
    assert corrected.supersedes_id == rec.id
    assert corrected.value == "bun"

    # Old record's state flipped
    old = repo.get_record(session, rec.id)
    assert old.state == MemoryState.SUPERSEDED

    # --- 5. Client B re-searches — reads new value, old excluded ---
    results_after, trace_after = service.search(session, ctx_b, "package-manager", limit=10)
    session.commit()

    assert len(results_after) == 1, "old superseded record leaked into default search"
    assert results_after[0].record.id == corrected.id
    assert results_after[0].record.value == "bun"

    # New trace recorded
    assert corrected.id in trace_after.returned_ids
    assert trace_after.id != trace.id


def test_projection_rebuildable(session):
    """Drop projection, replay events, verify state restored (spec §10 invariant)."""
    ctx = _ctx("client-a", project_id="demo")
    rec1 = service.propose(
        session, ctx,
        service.ProposeInput(
            content="preference 1",
            kind=MemoryKind.PREFERENCE,
            scope=ctx.scope,
            auto_approve=True,
        ),
    )
    session.commit()
    service.correct(
        session, ctx,
        service.CorrectInput(memory_id=rec1.id, content="preference 1 corrected"),
    )
    session.commit()

    # Wipe projection
    session.query(repo.MemoryRow).delete()  # type: ignore[attr-defined]
    session.commit()
    assert repo.list_records(session) == []

    # Rebuild from events
    count = repo.rebuild_projection(session)
    session.commit()
    assert count >= 2, f"expected ≥2 records after rebuild, got {count}"

    # Old one superseded, new one active
    recs = repo.list_records(session)
    states = [r.state for r in recs]
    assert MemoryState.SUPERSEDED in states
    assert MemoryState.ACTIVE in states


def test_secret_detection_blocks_write(session):
    """Credentials must be refused at write (spec §10)."""
    ctx = _ctx("client-a", project_id="demo")
    with pytest.raises(ValueError, match="credential"):
        service.propose(
            session, ctx,
            service.ProposeInput(
                content="My key: sk-1234567890abcdefghijklmnop1234567890abcdefghij",
                kind=MemoryKind.FACT,
                scope=ctx.scope,
            ),
        )
