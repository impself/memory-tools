"""Domain service — propose, search, correct, approve, revoke, quarantine, purge.

State machine:
  propose  → candidate
  approve  → active
  correct  → new record active + old superseded (event chain preserved)
  quarantine → quarantined
  revoke   → revoked
  purge    → projection deleted + scrubbed tombstone event

Auto-approve is implemented as propose + approve, where approve is recorded
with ActorType.SYSTEM and a policy_id. This keeps online state and replayed
state identical (spec §10 invariant).

Transaction boundary: callers (HTTP/MCP) own commit. Service methods never
commit.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from memory_workbench.domain.errors import (
    InvalidTransition,
    MemoryError,
    MemoryNotFound,
    ScopeViolation,
    SecretContent,
)
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

_DEFAULT_AUTO_APPROVE_POLICY = "default-auto-approve"


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


def _ensure_not_secret(content: str) -> None:
    if detect_sensitivity(content) == MemorySensitivity.SECRET:
        raise SecretContent("content matches a credential pattern; refused")


def _redact_trace_query(query: str) -> str:
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
    return f"[redacted sha256={digest} length={len(query)}]"


def _ensure_visible(record: MemoryRecord, ctx: CallerContext) -> None:
    if not ctx.scope.can_read(record.scope):
        raise ScopeViolation(
            f"caller scope {ctx.scope.level.value} cannot read "
            f"memory at scope {record.scope.level.value}"
        )


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
    valid_from: datetime | None = None
    valid_until: datetime | None = None
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


# --- state machine helpers ----------------------------------------------


_LEGAL_TRANSITIONS: dict[MemoryState, set[EventType]] = {
    MemoryState.CANDIDATE: {
        EventType.APPROVED,
        EventType.QUARANTINED,
        EventType.REVOKED,
        EventType.PURGED,
    },
    MemoryState.ACTIVE: {
        EventType.SUPERSEDED,
        EventType.QUARANTINED,
        EventType.REVOKED,
        EventType.PURGED,
        EventType.CORRECTED,  # corrected-on records the new version inline
    },
    MemoryState.QUARANTINED: {
        EventType.APPROVED,   # back to active
        EventType.REVOKED,
        EventType.PURGED,
    },
    MemoryState.SUPERSEDED: {
        EventType.PURGED,
    },
    MemoryState.REVOKED: {
        EventType.PURGED,
    },
}


def _assert_transition(state: MemoryState, event_type: EventType) -> None:
    allowed = _LEGAL_TRANSITIONS.get(state, set())
    if event_type not in allowed:
        raise InvalidTransition(
            f"event {event_type.value} not allowed from state {state.value}"
        )


# --- write operations ---------------------------------------------------


def propose(session: Session, ctx: CallerContext, inp: ProposeInput) -> MemoryRecord:
    """Append PROPOSED event + candidate projection. Auto-approve chains APPROVED."""
    _ensure_not_secret(inp.content)

    now = utcnow()
    valid_from = inp.valid_from or now
    memory_id = _new_id("mem")
    source_id = inp.source_id or ctx.client_id
    actor_id = inp.actor_id or ctx.agent_id or ctx.client_id
    sensitivity = detect_sensitivity(inp.content)

    scope_payload = inp.scope.model_dump(mode="json")
    payload = {
        "content": inp.content,
        "kind": inp.kind.value,
        "subject": inp.subject,
        "predicate": inp.predicate,
        "value": inp.value,
        "scope": scope_payload,
        "confidence": inp.confidence,
        "sensitivity": sensitivity.value,
        "valid_from": valid_from.isoformat(),
        "valid_until": inp.valid_until.isoformat() if inp.valid_until else None,
    }

    proposed_ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=memory_id,
        event_type=EventType.PROPOSED,
        actor_type=ActorType.AGENT,
        actor_id=actor_id,
        source_id=source_id,
        timestamp=now,
        payload=payload,
        previous_event_id=None,
    )
    repo.append_event(session, proposed_ev)

    record = MemoryRecord(
        id=memory_id,
        content=inp.content,
        kind=inp.kind,
        subject=inp.subject,
        predicate=inp.predicate,
        value=inp.value,
        scope=inp.scope,
        state=MemoryState.CANDIDATE,
        confidence=inp.confidence,
        sensitivity=sensitivity,
        valid_from=valid_from,
        valid_until=inp.valid_until,
        source_id=source_id,
        supersedes_id=None,
        created_at=now,
        updated_at=now,
    )
    repo.upsert_projection(session, record)

    if inp.auto_approve:
        _approve_internal(
            session,
            record=record,
            prev_event_id=proposed_ev.event_id,
            actor_type=ActorType.SYSTEM,
            actor_id=_DEFAULT_AUTO_APPROVE_POLICY,
            source_id=source_id,
            when=now,
            policy_id=_DEFAULT_AUTO_APPROVE_POLICY,
        )
        record = repo.get_record(session, memory_id) or record

    return record


def _approve_internal(
    session: Session,
    *,
    record: MemoryRecord,
    prev_event_id: str | None,
    actor_type: ActorType,
    actor_id: str,
    source_id: str,
    when: datetime,
    policy_id: str | None,
) -> MemoryRecord:
    _assert_transition(record.state, EventType.APPROVED)
    ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=record.id,
        event_type=EventType.APPROVED,
        actor_type=actor_type,
        actor_id=actor_id,
        source_id=source_id,
        timestamp=when,
        payload={"policy_id": policy_id} if policy_id else {},
        previous_event_id=prev_event_id,
    )
    repo.append_event(session, ev)
    record.state = MemoryState.ACTIVE
    record.updated_at = when
    repo.upsert_projection(session, record)
    return record


def approve(
    session: Session,
    memory_id: str,
    *,
    actor_id: str = "user",
    actor_type: ActorType = ActorType.USER,
    policy_id: str | None = None,
    source_id: str = "manual",
) -> MemoryRecord:
    rec = repo.get_record(session, memory_id)
    if rec is None:
        raise MemoryNotFound(memory_id)
    return _approve_internal(
        session,
        record=rec,
        prev_event_id=repo.last_event_id(session, memory_id),
        actor_type=actor_type,
        actor_id=actor_id,
        source_id=source_id,
        when=utcnow(),
        policy_id=policy_id,
    )


def correct(session: Session, ctx: CallerContext, inp: CorrectInput) -> MemoryRecord:
    """Create a new ACTIVE record superseding inp.memory_id.

    Safety:
    - Secret-scan new content
    - Caller scope must be able to read old record
    - Old must not be REVOKED (only PURGED-able) or PURGED (already gone)
    """
    _ensure_not_secret(inp.content)

    old = repo.get_record(session, inp.memory_id)
    if old is None:
        raise MemoryNotFound(inp.memory_id)
    _ensure_visible(old, ctx)

    if old.state in {MemoryState.REVOKED, MemoryState.SUPERSEDED, MemoryState.QUARANTINED}:
        raise InvalidTransition(
            f"cannot correct memory in state {old.state.value}"
        )

    now = utcnow()
    new_id = _new_id("mem")
    source_id = inp.source_id or ctx.client_id
    actor_id = inp.actor_id or ctx.agent_id or ctx.client_id
    new_value = inp.value if inp.value is not None else old.value

    # 1) Mark old superseded
    _assert_transition(old.state, EventType.SUPERSEDED)
    sup_ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=old.id,
        event_type=EventType.SUPERSEDED,
        actor_type=ActorType.AGENT,
        actor_id=actor_id,
        source_id=source_id,
        timestamp=now,
        payload={"superseded_by": new_id, "reason": "user_corrected"},
        previous_event_id=repo.last_event_id(session, old.id),
    )
    repo.append_event(session, sup_ev)
    old.state = MemoryState.SUPERSEDED
    old.updated_at = now
    repo.upsert_projection(session, old)

    # 2) New CORRECTED event (treated as ACTIVE on fold)
    new_record = MemoryRecord(
        id=new_id,
        content=inp.content,
        kind=old.kind,
        subject=old.subject,
        predicate=old.predicate,
        value=new_value,
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
    corrected_ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=new_id,
        event_type=EventType.CORRECTED,
        actor_type=ActorType.AGENT,
        actor_id=actor_id,
        source_id=source_id,
        timestamp=now,
        payload={
            "content": inp.content,
            "kind": old.kind.value,
            "subject": old.subject,
            "predicate": old.predicate,
            "value": new_value,
            "scope": old.scope.model_dump(mode="json"),
            "confidence": old.confidence,
            "sensitivity": old.sensitivity.value,
            "valid_from": now.isoformat(),
            "valid_until": None,
            "supersedes_id": old.id,
        },
        previous_event_id=None,
    )
    repo.append_event(session, corrected_ev)
    repo.upsert_projection(session, new_record)
    return new_record


def revoke(
    session: Session,
    memory_id: str,
    *,
    actor_id: str = "user",
    source_id: str = "manual",
    reason: str | None = None,
) -> MemoryRecord:
    rec = repo.get_record(session, memory_id)
    if rec is None:
        raise MemoryNotFound(memory_id)
    _assert_transition(rec.state, EventType.REVOKED)
    now = utcnow()
    ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=memory_id,
        event_type=EventType.REVOKED,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        source_id=source_id,
        timestamp=now,
        payload={"reason": reason or "manual_revoke"},
        previous_event_id=repo.last_event_id(session, memory_id),
    )
    repo.append_event(session, ev)
    rec.state = MemoryState.REVOKED
    rec.updated_at = now
    repo.upsert_projection(session, rec)
    return rec


def quarantine(
    session: Session,
    memory_id: str,
    *,
    actor_id: str = "user",
    source_id: str = "manual",
    reason: str | None = None,
) -> MemoryRecord:
    rec = repo.get_record(session, memory_id)
    if rec is None:
        raise MemoryNotFound(memory_id)
    _assert_transition(rec.state, EventType.QUARANTINED)
    now = utcnow()
    ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=memory_id,
        event_type=EventType.QUARANTINED,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        source_id=source_id,
        timestamp=now,
        payload={"reason": reason or "manual_quarantine"},
        previous_event_id=repo.last_event_id(session, memory_id),
    )
    repo.append_event(session, ev)
    rec.state = MemoryState.QUARANTINED
    rec.updated_at = now
    repo.upsert_projection(session, rec)
    return rec


def purge(
    session: Session,
    memory_id: str,
    *,
    actor_id: str = "user",
    source_id: str = "manual",
) -> None:
    """Spec §10: remove content + projection + write contentless tombstone event."""
    rec = repo.get_record(session, memory_id)
    if rec is None:
        # Could already be purged. Tombstone must exist if so.
        if repo.has_tombstone(session, memory_id):
            return
        raise MemoryNotFound(memory_id)
    _assert_transition(rec.state, EventType.PURGED)
    now = utcnow()
    ev = MemoryEvent(
        event_id=_new_id("ev"),
        memory_id=memory_id,
        event_type=EventType.PURGED,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        source_id=source_id,
        timestamp=now,
        payload={"reason": "purge", "scrubbed_fields": ["content", "value", "subject", "predicate"]},
        previous_event_id=repo.last_event_id(session, memory_id),
    )
    repo.append_event(session, ev)
    repo.scrub_events_for_purge(session, memory_id)
    repo.delete_projection(session, memory_id)


# --- read operations ----------------------------------------------------


def search(
    session: Session,
    ctx: CallerContext,
    query: str,
    *,
    kinds: list[MemoryKind] | None = None,
    include_inactive: bool = False,
    limit: int = 20,
) -> tuple[list[SearchResult], RetrievalTrace]:
    """Scope filter first, then naive substring match. Writes a RetrievalTrace row.

    Does NOT commit — caller manages transaction.
    """
    t0 = time.perf_counter()
    q = (query or "").strip().lower()
    stmt = repo.select_search_query(
        include_inactive=include_inactive,
        at=utcnow(),
        kinds=kinds,
    )

    rows = session.execute(stmt).scalars().all()

    candidates: list[tuple[MemoryRecord, str]] = []
    for row in rows:
        rec = repo.row_to_record(row)
        if not ctx.scope.can_read(rec.scope):
            continue
        if q:
            haystacks = [
                ("subject", (rec.subject or "").lower()),
                ("predicate", (rec.predicate or "").lower()),
                ("value", (rec.value or "").lower()),
                ("content", rec.content.lower()),
            ]
            hit_field = next((name for name, h in haystacks if q in h), None)
            if hit_field is None:
                continue
            reason = f"{hit_field} match"
        else:
            reason = "scope-visible (no query)"
        candidates.append((rec, reason))

    candidates.sort(
        key=lambda kv: (
            -(kv[0].confidence or 0.0),  # confidence desc
            -kv[0].updated_at.timestamp(),  # recency desc
            kv[0].id,  # stable tie-breaker
        )
    )

    returned = candidates[:limit]

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    trace = RetrievalTrace(
        id=_new_id("tr"),
        timestamp=utcnow(),
        client_id=ctx.client_id,
        agent_id=ctx.agent_id,
        query=_redact_trace_query(query),
        scope=ctx.scope,
        candidate_ids=[c[0].id for c in candidates],
        returned_ids=[c[0].id for c in returned],
        hit_reasons={c[0].id: c[1] for c in returned},
        elapsed_ms=elapsed_ms,
    )
    repo.write_trace(session, trace)
    return [SearchResult(record=r, hit_reason=reason) for r, reason in returned], trace


def explain(session: Session, ctx: CallerContext, memory_id: str) -> dict[str, Any]:
    rec = repo.get_record(session, memory_id)
    if rec is None:
        if repo.has_tombstone(session, memory_id):
            return {"record": None, "purged": True, "events": []}
        raise MemoryNotFound(memory_id)
    _ensure_visible(rec, ctx)
    events = repo.list_events(session, memory_id)
    traces = repo.list_traces(session, limit=200)
    related = [t for t in traces if memory_id in t.returned_ids]
    return {
        "record": rec.model_dump(mode="json"),
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


__all__ = [
    "CorrectInput",
    "InvalidTransition",
    "MemoryError",
    "MemoryNotFound",
    "ProposeInput",
    "ScopeViolation",
    "SearchResult",
    "SecretContent",
    "approve",
    "correct",
    "detect_sensitivity",
    "explain",
    "propose",
    "purge",
    "quarantine",
    "revoke",
    "search",
]
