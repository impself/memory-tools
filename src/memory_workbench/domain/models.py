"""Domain models — MemoryRecord, MemoryEvent, MemoryScope, enums.

Pure dataclasses + Pydantic models. No DB, no IO. Spec §6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryKind(str, Enum):
    PREFERENCE = "preference"
    FACT = "fact"
    DECISION = "decision"
    CONSTRAINT = "constraint"
    PROCEDURE = "procedure"
    EXPERIENCE = "experience"


class MemoryState(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"
    REVOKED = "revoked"


class MemorySensitivity(str, Enum):
    NORMAL = "normal"
    PRIVATE = "private"
    SECRET = "secret"


class ScopeLevel(str, Enum):
    GLOBAL = "global"
    WORKSPACE = "workspace"
    PROJECT = "project"
    AGENT = "agent"
    SESSION = "session"


class EventType(str, Enum):
    PROPOSED = "memory.proposed"
    APPROVED = "memory.approved"
    CORRECTED = "memory.corrected"
    SUPERSEDED = "memory.superseded"
    QUARANTINED = "memory.quarantined"
    REVOKED = "memory.revoked"
    PURGED = "memory.purged"
    RETRIEVED = "memory.retrieved"
    EXPORTED = "memory.exported"


class ActorType(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class MemoryScope(BaseModel):
    """Caller context for a memory. Required on every propose/search.

    Level determines which id fields are meaningful:
      global     — no ids
      workspace  — workspace_id
      project    — workspace_id? + project_id
      agent      — agent_id (+ optional workspace/project)
      session    — session_id (+ optional workspace/project/agent)
    """

    level: ScopeLevel
    workspace_id: str | None = None
    project_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None

    def matches(self, other: MemoryScope) -> bool:
        """Does `other` (a stored record's scope) satisfy `self` (query scope)?

        Rule: query scope narrows. Stored broader scopes are visible from narrower
        queries within the same id lineage. Stored narrower scopes are invisible
        to broader queries.
        """
        # Level precedence: global > workspace > project > agent > session
        levels = list(ScopeLevel)
        q_idx = levels.index(self.level)
        s_idx = levels.index(other.level)
        # Stored must be at same level or broader
        if s_idx > q_idx:
            return False
        # If stored is broader (smaller idx), its ids must be compatible
        # with query ids along the path.
        if other.level == ScopeLevel.GLOBAL:
            return True
        if self.workspace_id is not None and other.workspace_id not in (None, self.workspace_id):
            return False
        if other.level == ScopeLevel.WORKSPACE:
            return True
        if self.project_id is not None and other.project_id not in (None, self.project_id):
            return False
        if other.level == ScopeLevel.PROJECT:
            return True
        if self.agent_id is not None and other.agent_id not in (None, self.agent_id):
            return False
        if other.level == ScopeLevel.AGENT:
            return True
        if self.session_id is not None and other.session_id not in (None, self.session_id):
            return False
        return True


class MemoryRecord(BaseModel):
    """Current queryable projection folded from events."""

    id: str
    content: str
    kind: MemoryKind
    subject: str | None = None
    predicate: str | None = None
    value: str | None = None
    scope: MemoryScope
    state: MemoryState
    confidence: float | None = None
    sensitivity: MemorySensitivity = MemorySensitivity.NORMAL
    valid_from: datetime = Field(default_factory=utcnow)
    valid_until: datetime | None = None
    source_id: str
    supersedes_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def conflict_key(self) -> tuple[str | None, str | None, MemoryScope]:
        """Deterministic key for structured conflict detection."""
        return (self.subject, self.predicate, self.scope)


class MemoryEvent(BaseModel):
    """Immutable event in the ledger."""

    event_id: str
    memory_id: str
    event_type: EventType
    actor_type: ActorType
    actor_id: str
    source_id: str
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
    previous_event_id: str | None = None


class CallerContext(BaseModel):
    """Who is calling — MCP client, agent, workspace, project, session."""

    client_id: str
    agent_id: str | None = None
    scope: MemoryScope


class RetrievalTrace(BaseModel):
    """One search call's audit record."""

    id: str
    timestamp: datetime = Field(default_factory=utcnow)
    client_id: str
    agent_id: str | None
    query: str
    scope: MemoryScope
    candidate_ids: list[str] = Field(default_factory=list)
    returned_ids: list[str] = Field(default_factory=list)
    hit_reasons: dict[str, str] = Field(default_factory=dict)
    elapsed_ms: int
    error: str | None = None


# Convenience: states that block a memory from default search results
VISIBLE_STATES = {MemoryState.ACTIVE}

# States considered terminal for default projections
TERMINAL_STATES = {MemoryState.SUPERSEDED, MemoryState.REVOKED}
