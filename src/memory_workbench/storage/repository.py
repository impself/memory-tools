"""Event log + projection repository.

Append-only event history, with payload redaction only during hard purge.
Projection mutated in same transaction. Tracer-bullet:
single-process SQLite, no concurrency fan-out.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from memory_workbench.domain.models import (
    ActorType,
    AgentAsset,
    AgentAssetStatus,
    AgentEndpoint,
    EndpointPlatform,
    EventType,
    MemoryEvent,
    MemoryGrant,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryState,
    Project,
    ProjectMembership,
    RetrievalTrace,
    ScopeLevel,
    SyncMode,
    utcnow,
)
from memory_workbench.storage.tables import (
    AgentAssetRow,
    AgentEndpointRow,
    EventRow,
    MemoryGrantRow,
    MemoryRow,
    ProjectMembershipRow,
    ProjectRow,
    TraceRow,
)

_EVENT_TYPE_ORDER = {
    EventType.PROPOSED.value: 0,
    EventType.CORRECTED.value: 0,
    EventType.APPROVED.value: 1,
    EventType.SUPERSEDED.value: 2,
    EventType.QUARANTINED.value: 2,
    EventType.REVOKED.value: 3,
    EventType.PURGED.value: 4,
}


def _event_type_order() -> ColumnElement[int]:
    """Deterministic ordering for events that share a transaction timestamp."""
    return case(_EVENT_TYPE_ORDER, value=EventRow.event_type, else_=99)


# Public re-exports for service layer
def select_all_active_query() -> Select[tuple[MemoryRow]]:
    """Default search base: ACTIVE records."""
    return select(MemoryRow).where(MemoryRow.state == MemoryState.ACTIVE.value)


def select_all_query() -> Select[tuple[MemoryRow]]:
    """All records regardless of state."""
    return select(MemoryRow)


def select_search_query(
    *,
    include_inactive: bool,
    at: datetime,
    kinds: list[MemoryKind] | None = None,
) -> Select[tuple[MemoryRow]]:
    """Build the state and validity-filtered base query for retrieval."""
    stmt = select_all_query() if include_inactive else select_all_active_query()
    stmt = stmt.where(
        MemoryRow.valid_from <= at,
        or_(MemoryRow.valid_until.is_(None), MemoryRow.valid_until > at),
    )
    if kinds:
        stmt = stmt.where(MemoryRow.kind.in_([kind.value for kind in kinds]))
    return stmt


def row_to_record(row: MemoryRow) -> MemoryRecord:
    return _row_to_record(row)


def last_event_id(session: Session, memory_id: str) -> str | None:
    return _last_event_id_for(session, memory_id)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _asset_from_row(row: AgentAssetRow) -> AgentAsset:
    return AgentAsset(
        id=row.id,
        name=row.name,
        description=row.description,
        role_tags=row.role_tags,
        default_sync_mode=SyncMode(row.default_sync_mode),
        trust_level=row.trust_level,
        status=AgentAssetStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _endpoint_from_row(row: AgentEndpointRow) -> AgentEndpoint:
    return AgentEndpoint(
        id=row.id,
        asset_id=row.asset_id,
        client_id=row.client_id,
        platform=EndpointPlatform(row.platform),
        display_name=row.display_name,
        status=AgentAssetStatus(row.status),
        created_at=row.created_at,
    )


def _project_from_row(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        workspace_id=row.workspace_id,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _membership_from_row(row: ProjectMembershipRow) -> ProjectMembership:
    return ProjectMembership(
        asset_id=row.asset_id,
        project_id=row.project_id,
        role=row.role,
        sync_mode=SyncMode(row.sync_mode),
        created_at=row.created_at,
    )


def _grant_from_row(row: MemoryGrantRow) -> MemoryGrant:
    return MemoryGrant(
        id=row.id,
        memory_id=row.memory_id,
        asset_id=row.asset_id,
        sync_mode=SyncMode(row.sync_mode),
        created_at=row.created_at,
    )


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
        .order_by(
            EventRow.timestamp.desc(),
            _event_type_order().desc(),
            EventRow.event_id.desc(),
        )
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


# --- AgentAsset control plane --------------------------------------------


def create_agent_asset(
    session: Session,
    *,
    name: str,
    description: str | None,
    role_tags: list[str],
    default_sync_mode: SyncMode,
    trust_level: str = "standard",
) -> AgentAsset:
    now = utcnow()
    row = AgentAssetRow(
        id=_new_id("asset"),
        name=name,
        description=description,
        role_tags=role_tags,
        default_sync_mode=default_sync_mode.value,
        trust_level=trust_level,
        status=AgentAssetStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    return _asset_from_row(row)


def get_agent_asset(session: Session, asset_id: str) -> AgentAsset | None:
    row = session.get(AgentAssetRow, asset_id)
    return _asset_from_row(row) if row else None


def list_agent_assets(session: Session) -> list[AgentAsset]:
    rows = session.execute(
        select(AgentAssetRow).order_by(AgentAssetRow.updated_at.desc(), AgentAssetRow.id)
    ).scalars().all()
    return [_asset_from_row(row) for row in rows]


def create_project(
    session: Session,
    *,
    project_id: str,
    name: str,
    workspace_id: str | None,
    description: str | None,
) -> Project:
    now = utcnow()
    row = ProjectRow(
        id=project_id,
        name=name,
        workspace_id=workspace_id,
        description=description,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    return _project_from_row(row)


def get_project(session: Session, project_id: str) -> Project | None:
    row = session.get(ProjectRow, project_id)
    return _project_from_row(row) if row else None


def list_projects(session: Session) -> list[Project]:
    rows = session.execute(select(ProjectRow).order_by(ProjectRow.name, ProjectRow.id)).scalars().all()
    return [_project_from_row(row) for row in rows]


def add_project_membership(
    session: Session,
    *,
    asset_id: str,
    project_id: str,
    role: str | None,
    sync_mode: SyncMode,
) -> ProjectMembership:
    row = ProjectMembershipRow(
        asset_id=asset_id,
        project_id=project_id,
        role=role,
        sync_mode=sync_mode.value,
        created_at=utcnow(),
    )
    session.add(row)
    return _membership_from_row(row)


def list_asset_memberships(session: Session, asset_id: str) -> list[ProjectMembership]:
    rows = session.execute(
        select(ProjectMembershipRow)
        .where(ProjectMembershipRow.asset_id == asset_id)
        .order_by(ProjectMembershipRow.created_at, ProjectMembershipRow.project_id)
    ).scalars().all()
    return [_membership_from_row(row) for row in rows]


def list_project_memberships(session: Session, project_id: str) -> list[ProjectMembership]:
    rows = session.execute(
        select(ProjectMembershipRow)
        .where(ProjectMembershipRow.project_id == project_id)
        .order_by(ProjectMembershipRow.created_at, ProjectMembershipRow.asset_id)
    ).scalars().all()
    return [_membership_from_row(row) for row in rows]


def add_agent_endpoint(
    session: Session,
    *,
    asset_id: str,
    client_id: str,
    platform: EndpointPlatform,
    display_name: str | None,
) -> AgentEndpoint:
    row = AgentEndpointRow(
        id=_new_id("endpoint"),
        asset_id=asset_id,
        client_id=client_id,
        platform=platform.value,
        display_name=display_name,
        status=AgentAssetStatus.ACTIVE.value,
        created_at=utcnow(),
    )
    session.add(row)
    return _endpoint_from_row(row)


def list_asset_endpoints(session: Session, asset_id: str) -> list[AgentEndpoint]:
    rows = session.execute(
        select(AgentEndpointRow)
        .where(AgentEndpointRow.asset_id == asset_id)
        .order_by(AgentEndpointRow.created_at, AgentEndpointRow.id)
    ).scalars().all()
    return [_endpoint_from_row(row) for row in rows]


def add_memory_grant(
    session: Session,
    *,
    asset_id: str,
    memory_id: str,
    sync_mode: SyncMode,
) -> MemoryGrant:
    row = MemoryGrantRow(
        id=_new_id("grant"),
        memory_id=memory_id,
        asset_id=asset_id,
        sync_mode=sync_mode.value,
        created_at=utcnow(),
    )
    session.add(row)
    return _grant_from_row(row)


def list_asset_grants(session: Session, asset_id: str) -> list[MemoryGrant]:
    rows = session.execute(
        select(MemoryGrantRow)
        .where(MemoryGrantRow.asset_id == asset_id)
        .order_by(MemoryGrantRow.created_at, MemoryGrantRow.id)
    ).scalars().all()
    return [_grant_from_row(row) for row in rows]


def list_asset_visible_memories(session: Session, asset_id: str) -> list[MemoryRecord]:
    """Compute visibility from grants and memberships; never duplicate memory rows."""
    memberships = list_asset_memberships(session, asset_id)
    project_ids = {membership.project_id for membership in memberships}
    projects = [get_project(session, project_id) for project_id in project_ids]
    workspace_ids = {project.workspace_id for project in projects if project and project.workspace_id}
    granted_ids = {grant.memory_id for grant in list_asset_grants(session, asset_id)}
    rows = session.execute(
        select_search_query(include_inactive=False, at=utcnow())
    ).scalars().all()

    visible: list[MemoryRecord] = []
    for row in rows:
        record = _row_to_record(row)
        scope = record.scope
        if record.id in granted_ids or scope.level == ScopeLevel.GLOBAL or (scope.level == ScopeLevel.WORKSPACE and scope.workspace_id in workspace_ids) or (scope.level == ScopeLevel.PROJECT and scope.project_id in project_ids) or (scope.level == ScopeLevel.AGENT and scope.agent_id == asset_id):
            visible.append(record)

    return sorted(visible, key=lambda record: (-record.updated_at.timestamp(), record.id))


def list_events(session: Session, memory_id: str) -> list[MemoryEvent]:
    stmt = (
        select(EventRow)
        .where(EventRow.memory_id == memory_id)
        .order_by(
            EventRow.timestamp.asc(),
            _event_type_order().asc(),
            EventRow.event_id.asc(),
        )
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
    """Return any ACTIVE record sharing subject+predicate whose scope is visible
    to the caller's `scope`."""
    stmt = select(MemoryRow).where(
        MemoryRow.subject == subject,
        MemoryRow.predicate == predicate,
        MemoryRow.state == MemoryState.ACTIVE.value,
    )
    rows = session.execute(stmt).scalars().all()
    for row in rows:
        rec = _row_to_record(row)
        if scope.can_read(rec.scope):
            return rec
    return None


def delete_projection(session: Session, memory_id: str) -> None:
    """Remove the MemoryRow for a purged memory. Tombstone lives in events."""
    row = session.get(MemoryRow, memory_id)
    if row is not None:
        session.delete(row)


def scrub_events_for_purge(session: Session, memory_id: str) -> None:
    """Spec §10: remove content/value from all prior event payloads for this memory.

    Keeps the event id + type + actor + timestamp + relations; zeroes the
    text fields so rebuild never resurrects content.
    """
    stmt = select(EventRow).where(EventRow.memory_id == memory_id)
    rows = session.execute(stmt).scalars().all()
    scrub_fields = ("content", "value", "subject", "predicate")
    for row in rows:
        if not row.payload:
            continue
        new_payload = dict(row.payload)
        for field in scrub_fields:
            if field in new_payload:
                new_payload[field] = None
        row.payload = new_payload


def has_tombstone(session: Session, memory_id: str) -> bool:
    """True if event ledger contains a PURGED event for this memory."""
    stmt = select(EventRow).where(
        EventRow.memory_id == memory_id,
        EventRow.event_type == EventType.PURGED.value,
    )
    return session.execute(stmt).first() is not None


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
    session.query(MemoryRow).delete()

    # Group events by memory_id in chronological order
    stmt = select(EventRow).order_by(
        EventRow.timestamp.asc(),
        _event_type_order().asc(),
        EventRow.event_id.asc(),
    )
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
    """Apply events in order. Returns dict for row, or None if purged/empty.

    PROPOSED/CORRECTED carry the content payload; APPROVED/QUARANTINED/etc
    are state-only transitions and preserve the prior payload.
    """
    state: dict[str, Any] | None = None
    for ev in events:
        et = EventType(ev.event_type)
        if et == EventType.PURGED:
            return None
        if et in (EventType.PROPOSED, EventType.CORRECTED):
            p = ev.payload
            state = {
                "id": memory_id,
                "content": p["content"],
                "kind": p["kind"],
                "subject": p.get("subject"),
                "predicate": p.get("predicate"),
                "value": p.get("value"),
                "scope": p["scope"],
                "state": (
                    MemoryState.CANDIDATE.value
                    if et == EventType.PROPOSED
                    else MemoryState.ACTIVE.value
                ),
                "confidence": p.get("confidence"),
                "sensitivity": p.get("sensitivity", MemorySensitivity.NORMAL.value),
                "valid_from": p.get("valid_from", ev.timestamp.isoformat()),
                "valid_until": p.get("valid_until"),
                "source_id": ev.source_id,
                "supersedes_id": p.get("supersedes_id"),
                "created_at": ev.timestamp.isoformat(),
                "updated_at": ev.timestamp.isoformat(),
            }
        elif et == EventType.APPROVED:
            if state is not None:
                state["state"] = MemoryState.ACTIVE.value
                state["updated_at"] = ev.timestamp.isoformat()
        elif et == EventType.SUPERSEDED:
            if state is not None:
                state["state"] = MemoryState.SUPERSEDED.value
                state["updated_at"] = ev.timestamp.isoformat()
        elif et == EventType.QUARANTINED:
            if state is not None:
                state["state"] = MemoryState.QUARANTINED.value
                state["updated_at"] = ev.timestamp.isoformat()
        elif et == EventType.REVOKED:
            if state is not None:
                state["state"] = MemoryState.REVOKED.value
                state["updated_at"] = ev.timestamp.isoformat()
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
