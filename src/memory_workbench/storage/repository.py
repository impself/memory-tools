"""Event log + projection repository.

Append-only events. Projection mutated in same transaction. Tracer-bullet:
single-process SQLite, no concurrency fan-out.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from memory_workbench.domain.models import (
    ActorType,
    EventType,
    MemoryEvent,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryState,
    RetrievalTrace,
    ScopeLevel,
)
from memory_workbench.storage.tables import EventRow, MemoryRow, TraceRow


# Public re-exports for service layer
def select_all_active_query():
    """Default search base: ACTIVE records."""
    return select(MemoryRow).where(MemoryRow.state == MemoryState.ACTIVE.value)


def select_all_query():
    """All records regardless of state."""
    return select(MemoryRow)


def row_to_record(row: MemoryRow) -> MemoryRecord:
    return _row_to_record(row)


def last_event_id(session: Session, memory_id: str) -> str | None:
    return _last_event_id_for(session, memory_id)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _scope_to_json(scope: MemoryScope) -> dict[str, Any]:
    return {
        "level": scope.level.value,
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "agent_id": scope.agent_id,
        "session_id": scope.session_id,
    }


def _scope_from_json(data: dict[str, Any]) -> MemoryScope:
    return MemoryScope(
        level=ScopeLevel(data["level"]),
        workspace_id=data.get("workspace_id"),
        project_id=data.get("project_id"),
        agent_id=data.get("agent_id"),
        session_id=data.get("session_id"),
    )


def _row_to_record(row: MemoryRow) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        content=row.content,
        kind=MemoryKind(row.kind),
        subject=row.subject,
        predicate=row.predicate,
        value=row.value,
        scope=_scope_from_json(row.scope_json),
        state=MemoryState(row.state),
        confidence=row.confidence,
        sensitivity=MemorySensitivity(row.sensitivity),
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        source_id=row.source_id,
        supersedes_id=row.supersedes_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _event_row_from_model(ev: MemoryEvent) -> EventRow:
    return EventRow(
        event_id=ev.event_id,
        memory_id=ev.memory_id,
        event_type=ev.event_type.value,
        actor_type=ev.actor_type.value,
        actor_id=ev.actor_id,
        source_id=ev.source_id,
        timestamp=ev.timestamp,
        payload=ev.payload,
        previous_event_id=ev.previous_event_id,
    )


def _last_event_id_for(session: Session, memory_id: str) -> str | None:
    stmt = (
        select(EventRow)
        .where(EventRow.memory_id == memory_id)
        .order_by(EventRow.timestamp.desc())
    )
    row = session.execute(stmt).first()
    return row[0].event_id if row else None


def append_event(session: Session, ev: MemoryEvent) -> None:
    """Append event row. Idempotent on event_id."""
    session.add(_event_row_from_model(ev))


def upsert_projection(session: Session, record: MemoryRecord) -> None:
    """Insert or update the MemoryRow projection."""
    row = session.get(MemoryRow, record.id)
    if row is None:
        row = MemoryRow(id=record.id)
        session.add(row)
    row.content = record.content
    row.kind = record.kind.value
    row.subject = record.subject
    row.predicate = record.predicate
    row.value = record.value
    row.scope_json = _scope_to_json(record.scope)
    row.state = record.state.value
    row.confidence = record.confidence
    row.sensitivity = record.sensitivity.value
    row.valid_from = record.valid_from
    row.valid_until = record.valid_until
    row.source_id = record.source_id
    row.supersedes_id = record.supersedes_id
    row.created_at = record.created_at
    row.updated_at = record.updated_at


def get_record(session: Session, memory_id: str) -> MemoryRecord | None:
    row = session.get(MemoryRow, memory_id)
    return _row_to_record(row) if row else None


def list_records(
    session: Session,
    *,
    state: MemoryState | None = None,
    kind: MemoryKind | None = None,
    limit: int = 200,
) -> list[MemoryRecord]:
    stmt = select(MemoryRow).order_by(MemoryRow.updated_at.desc()).limit(limit)
    if state is not None:
        stmt = stmt.where(MemoryRow.state == state.value)
    if kind is not None:
        stmt = stmt.where(MemoryRow.kind == kind.value)
    rows = session.execute(stmt).scalars().all()
    return [_row_to_record(r) for r in rows]


def list_events(session: Session, memory_id: str) -> list[MemoryEvent]:
    stmt = (
        select(EventRow)
        .where(EventRow.memory_id == memory_id)
        .order_by(EventRow.timestamp.asc())
    )
    rows = session.execute(stmt).scalars().all()
    return [
        MemoryEvent(
            event_id=r.event_id,
            memory_id=r.memory_id,
            event_type=EventType(r.event_type),
            actor_type=ActorType(r.actor_type),
            actor_id=r.actor_id,
            source_id=r.source_id,
            timestamp=r.timestamp,
            payload=r.payload,
            previous_event_id=r.previous_event_id,
        )
        for r in rows
    ]


def find_active_conflict(
    session: Session,
    *,
    subject: str,
    predicate: str,
    scope: MemoryScope,
) -> MemoryRecord | None:
    """Return any ACTIVE record sharing subject+predicate whose scope matches."""
    stmt = select(MemoryRow).where(
        MemoryRow.subject == subject,
        MemoryRow.predicate == predicate,
        MemoryRow.state == MemoryState.ACTIVE.value,
    )
    rows = session.execute(stmt).scalars().all()
    for row in rows:
        rec = _row_to_record(row)
        if rec.scope.matches(scope) or scope.matches(rec.scope):
            return rec
    return None


def write_trace(session: Session, trace: RetrievalTrace) -> None:
    session.add(
        TraceRow(
            id=trace.id,
            timestamp=trace.timestamp,
            client_id=trace.client_id,
            agent_id=trace.agent_id,
            query=trace.query,
            scope_json=_scope_to_json(trace.scope),
            candidate_ids=trace.candidate_ids,
            returned_ids=trace.returned_ids,
            hit_reasons=trace.hit_reasons,
            elapsed_ms=trace.elapsed_ms,
            error=trace.error,
        )
    )


def list_traces(session: Session, limit: int = 50) -> list[RetrievalTrace]:
    stmt = (
        select(TraceRow)
        .order_by(TraceRow.timestamp.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).scalars().all()
    return [
        RetrievalTrace(
            id=r.id,
            timestamp=r.timestamp,
            client_id=r.client_id,
            agent_id=r.agent_id,
            query=r.query,
            scope=_scope_from_json(r.scope_json),
            candidate_ids=r.candidate_ids,
            returned_ids=r.returned_ids,
            hit_reasons=r.hit_reasons,
            elapsed_ms=r.elapsed_ms,
            error=r.error,
        )
        for r in rows
    ]


def rebuild_projection(session: Session) -> int:
    """Rebuild all MemoryRow from events. Returns count.

    Purged events leave no row. Used by tests to verify rebuildability.
    """
    session.query(MemoryRow).delete()  # type: ignore[attr-defined]

    # Group events by memory_id in chronological order
    stmt = select(EventRow).order_by(EventRow.timestamp.asc())
    events = session.execute(stmt).scalars().all()

    per_memory: dict[str, list[EventRow]] = {}
    for ev in events:
        per_memory.setdefault(ev.memory_id, []).append(ev)

    count = 0
    for memory_id, evs in per_memory.items():
        latest = _fold_events_to_record(memory_id, evs)
        if latest is not None:
            session.add(_projection_row_from_folded(latest))
            count += 1
    return count


def _fold_events_to_record(
    memory_id: str, events: list[EventRow]
) -> dict[str, Any] | None:
    """Apply events in order. Returns dict for row, or None if purged/empty."""
    state: dict[str, Any] | None = None
    for ev in events:
        et = EventType(ev.event_type)
        if et == EventType.PURGED:
            return None
        if et in (EventType.PROPOSED, EventType.APPROVED, EventType.CORRECTED):
            p = ev.payload
            state = {
                "id": memory_id,
                "content": p["content"],
                "kind": p["kind"],
                "subject": p.get("subject"),
                "predicate": p.get("predicate"),
                "value": p.get("value"),
                "scope": p["scope"],
                "state": MemoryState.ACTIVE.value if et != EventType.PROPOSED else MemoryState.CANDIDATE.value,
                "confidence": p.get("confidence"),
                "sensitivity": p.get("sensitivity", MemorySensitivity.NORMAL.value),
                "valid_from": p.get("valid_from", ev.timestamp.isoformat()),
                "valid_until": p.get("valid_until"),
                "source_id": ev.source_id,
                "supersedes_id": p.get("supersedes_id"),
                "created_at": ev.timestamp.isoformat(),
                "updated_at": ev.timestamp.isoformat(),
            }
        elif et == EventType.SUPERSEDED:
            if state is not None:
                state["state"] = MemoryState.SUPERSEDED.value
                state["updated_at"] = ev.timestamp.isoformat()
        elif et == EventType.QUARANTINED:
            if state is not None:
                state["state"] = MemoryState.QUARANTINED.value
        elif et == EventType.REVOKED:
            if state is not None:
                state["state"] = MemoryState.REVOKED.value
    return state


def _projection_row_from_folded(data: dict[str, Any]) -> MemoryRow:
    scope = data["scope"]
    return MemoryRow(
        id=data["id"],
        content=data["content"],
        kind=data["kind"],
        subject=data["subject"],
        predicate=data["predicate"],
        value=data["value"],
        scope_json=scope,
        state=data["state"],
        confidence=data["confidence"],
        sensitivity=data["sensitivity"],
        valid_from=datetime.fromisoformat(data["valid_from"]),
        valid_until=datetime.fromisoformat(data["valid_until"]) if data["valid_until"] else None,
        source_id=data["source_id"],
        supersedes_id=data["supersedes_id"],
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )
