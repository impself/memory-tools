"""Domain service — propose, search, correct. Pure logic over repository.

State machine (tracer-bullet subset):
  propose   → candidate (default) or active if auto-approve + low risk
  approve   → active
  correct   → new record active, old record superseded (event chain preserved)
  revoke    → revoked

Service receives a Session (managed by caller). Idempotent on event_id
(checked by SQLite primary key).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from memory_workbench.domain.models import (
    ActorType,
    CallerContext,
    EventType,
    MemoryEvent,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryState,
    RetrievalTrace,
    utcnow,
)
from memory_workbench.storage import repository as repo


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


# --- sensitivity scan ----------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),                  # OpenAI-style
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),                 # GitHub PAT
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),    # PEM
    re.compile(r"AKIA[0-9A-Z]{12,}"),                    # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),         # Slack token
]


def detect_sensitivity(content: str) -> MemorySensitivity:
    """Mark SECRET if matches credential patterns. Free-text heuristics only."""
    for pat in _SECRET_PATTERNS:
        if pat.search(content):
            return MemorySensitivity.SECRET
    return MemorySensitivity.NORMAL


# --- DTOs ----------------------------------------------------------------


@dataclass
class ProposeInput:
    content: str
    kind: MemoryKind
    scope: MemoryScope
    subject: str | None = None
    predicate: str | None = None
    value: str | None = None
    confidence: float | None = None
    auto_approve: bool = False
    source_id: str | None = None
    actor_id: str | None = None


@dataclass
class SearchResult:
    record: MemoryRecord
    hit_reason: str


@dataclass
class CorrectInput:
    memory_id: str
    content: str
    value: str | None = None
    actor_id: str | None = None
    source_id: str | None = None


# --- service -------------------------------------------------------------


def propose(session: Session, ctx: CallerContext, inp: ProposeInput) -> MemoryRecord:
    """Append proposed event + projection. Returns the new record."""
    now = utcnow()
    sensitivity = detect_sensitivity(inp.content)

    # Reject secrets at write time (tracer-bullet policy)
    if sensitivity == MemorySensitivity.SECRET:
        raise ValueError("Content looks like a credential; refusing to store as memory.")

    memory_id = _new_id("mem")
    source_id = inp.source_id or ctx.client_id

    state = MemoryState.ACTIVE if inp.auto_approve else MemoryState.CANDIDATE

    record = MemoryRecord(
        id=memory_id,
        content=inp.content,
        kind=inp.kind,
        subject=inp.subject,
        predicate=inp.predicate,
        value=inp.value,
        scope=inp.scope,
        state=state,
        confidence=inp.confidence,
        sensitivity=sensitivity,
        valid_from=now,
        source_id=source_id,
        supersedes_id=None,
        created_at=now,
        updated_at=now,
    )

    ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=memory_id,
        event_type=EventType.PROPOSED,
        actor_type=ActorType.AGENT,
        actor_id=inp.actor_id or ctx.agent_id or ctx.client_id,
        source_id=source_id,
        timestamp=now,
        payload={
            "content": inp.content,
            "kind": inp.kind.value,
            "subject": inp.subject,
            "predicate": inp.predicate,
            "value": inp.value,
            "scope": record.scope.model_dump(mode="json"),
            "confidence": inp.confidence,
            "sensitivity": sensitivity.value,
            "valid_from": now.isoformat(),
            "valid_until": None,
        },
        previous_event_id=None,
    )
    repo.append_event(session, ev)
    repo.upsert_projection(session, record)
    return record


def search(
    session: Session,
    ctx: CallerContext,
    query: str,
    *,
    kinds: list[MemoryKind] | None = None,
    include_inactive: bool = False,
    limit: int = 20,
) -> tuple[list[SearchResult], RetrievalTrace]:
    """Scope filter first, then naive LIKE. Writes a RetrievalTrace row."""
    t0 = time.perf_counter()
    q = (query or "").strip().lower()
    stmt = (
        repo.select_all_active_query()
        if not include_inactive
        else repo.select_all_query()
    )

    # Filter by kind
    if kinds:
        stmt = stmt.where(repo.MemoryRow.kind.in_([k.value for k in kinds]))

    # Fetch candidates
    rows = session.execute(stmt).scalars().all()

    candidates: list[tuple[MemoryRecord, str]] = []
    for row in rows:
        rec = repo.row_to_record(row)
        if not rec.scope.matches(ctx.scope):
            continue
        if q:
            haystacks = [
                ("subject", (rec.subject or "").lower()),
                ("predicate", (rec.predicate or "").lower()),
                ("value", (rec.value or "").lower()),
                ("content", rec.content.lower()),
            ]
            hit_field = next(
                (name for name, h in haystacks if q in h),
                None,
            )
            if hit_field is None:
                continue
            reason = f"{hit_field} match"
        else:
            reason = "scope-visible (no query)"
        candidates.append((rec, reason))

    candidates.sort(key=lambda kv: (-1 if kv[0].confidence else 0, kv[0].updated_at))
    returned = candidates[:limit]

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    trace = RetrievalTrace(
        id=_new_id("tr"),
        timestamp=utcnow(),
        client_id=ctx.client_id,
        agent_id=ctx.agent_id,
        query=query,
        scope=ctx.scope,
        candidate_ids=[c[0].id for c in candidates],
        returned_ids=[c[0].id for c in returned],
        hit_reasons={c[0].id: c[1] for c in returned},
        elapsed_ms=elapsed_ms,
    )
    repo.write_trace(session, trace)
    session.commit()
    return [SearchResult(record=r, hit_reason=reason) for r, reason in returned], trace


def correct(session: Session, ctx: CallerContext, inp: CorrectInput) -> MemoryRecord:
    """Create a new active record superseding inp.memory_id.

    Old record's state flips to SUPERSEDED via a SUPERSEDED event. The new
    record inherits scope/kind/source; new content + value override.
    """
    old = repo.get_record(session, inp.memory_id)
    if old is None:
        raise ValueError(f"memory {inp.memory_id} not found")
    if old.state == MemoryState.REVOKED:
        raise ValueError("cannot correct a revoked memory")

    now = utcnow()
    new_id = _new_id("mem")
    source_id = inp.source_id or ctx.client_id

    new_record = MemoryRecord(
        id=new_id,
        content=inp.content,
        kind=old.kind,
        subject=old.subject,
        predicate=old.predicate,
        value=inp.value if inp.value is not None else old.value,
        scope=old.scope,
        state=MemoryState.ACTIVE,
        confidence=old.confidence,
        sensitivity=old.sensitivity,
        valid_from=now,
        valid_until=None,
        source_id=source_id,
        supersedes_id=old.id,
        created_at=now,
        updated_at=now,
    )

    # 1) Mark old superseded
    old_prev = repo.last_event_id(session, old.id)
    sup_ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=old.id,
        event_type=EventType.SUPERSEDED,
        actor_type=ActorType.AGENT,
        actor_id=inp.actor_id or ctx.agent_id or ctx.client_id,
        source_id=source_id,
        timestamp=now,
        payload={"superseded_by": new_id, "reason": "user_corrected"},
        previous_event_id=old_prev,
    )
    repo.append_event(session, sup_ev)

    # 2) Old projection: flip state
    old.state = MemoryState.SUPERSEDED
    old.updated_at = now
    repo.upsert_projection(session, old)

    # 3) New proposed-as-active event + projection
    proposed_ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=new_id,
        event_type=EventType.CORRECTED,
        actor_type=ActorType.AGENT,
        actor_id=inp.actor_id or ctx.agent_id or ctx.client_id,
        source_id=source_id,
        timestamp=now,
        payload={
            "content": inp.content,
            "kind": old.kind.value,
            "subject": old.subject,
            "predicate": old.predicate,
            "value": new_record.value,
            "scope": old.scope.model_dump(mode="json"),
            "confidence": old.confidence,
            "sensitivity": old.sensitivity.value,
            "valid_from": now.isoformat(),
            "valid_until": None,
            "supersedes_id": old.id,
        },
        previous_event_id=None,
    )
    repo.append_event(session, proposed_ev)
    repo.upsert_projection(session, new_record)
    return new_record


def explain(session: Session, memory_id: str) -> dict:
    """Return record + event timeline + recent traces that returned it."""
    rec = repo.get_record(session, memory_id)
    events = repo.list_events(session, memory_id)
    traces = repo.list_traces(session, limit=200)
    related = [t for t in traces if memory_id in t.returned_ids]
    return {
        "record": rec.model_dump(mode="json") if rec else None,
        "events": [e.model_dump(mode="json") for e in events],
        "recent_reads": [
            {
                "trace_id": t.id,
                "timestamp": t.timestamp.isoformat(),
                "client_id": t.client_id,
                "agent_id": t.agent_id,
                "query": t.query,
            }
            for t in related
        ],
    }
