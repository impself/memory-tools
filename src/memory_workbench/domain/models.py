"""Domain models — MemoryRecord, MemoryEvent, MemoryScope, enums.

Pure dataclasses + Pydantic models. No DB, no IO. Spec §6.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class MemoryKind(StrEnum):
    PREFERENCE = "preference"
    FACT = "fact"
    DECISION = "decision"
    CONSTRAINT = "constraint"
    PROCEDURE = "procedure"
    EXPERIENCE = "experience"


class MemoryState(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"
    REVOKED = "revoked"


class MemorySensitivity(StrEnum):
    NORMAL = "normal"
    PRIVATE = "private"
    SECRET = "secret"


class ScopeLevel(StrEnum):
    GLOBAL = "global"
    WORKSPACE = "workspace"
    PROJECT = "project"
    AGENT = "agent"
    SESSION = "session"


class SyncMode(StrEnum):
    """How a memory becomes available to an AgentAsset."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"


class AgentAssetStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class EndpointPlatform(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    CURSOR = "cursor"
    CUSTOM = "custom"


class EventType(StrEnum):
    PROPOSED = "memory.proposed"
    APPROVED = "memory.approved"
    CORRECTED = "memory.corrected"
    SUPERSEDED = "memory.superseded"
    QUARANTINED = "memory.quarantined"
    REVOKED = "memory.revoked"
    PURGED = "memory.purged"
    RETRIEVED = "memory.retrieved"
    EXPORTED = "memory.exported"


class ActorType(StrEnum):
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

    @model_validator(mode="after")
    def _validate_ids(self) -> MemoryScope:
        """Levels require their id; lower levels may carry parent ids."""
        if self.level == ScopeLevel.WORKSPACE and not self.workspace_id:
            raise ValueError("workspace scope requires workspace_id")
        if self.level == ScopeLevel.PROJECT and not self.project_id:
            raise ValueError("project scope requires project_id")
        if self.level == ScopeLevel.AGENT and not self.agent_id:
            raise ValueError("agent scope requires agent_id")
        if self.level == ScopeLevel.SESSION and not self.session_id:
            raise ValueError("session scope requires session_id")
        return self

    def can_read(self, stored: MemoryScope) -> bool:
        """Can the caller (self) read a record stored under `stored`?

        Semantics:
        - Caller at broader level cannot see narrower stored records
          (global caller does not see project-scoped records).
        - Caller at narrower level can see broader-or-equal stored records
          only if every id present in `stored` matches the caller's id.
          A None id in `stored` means "inherited from caller" (matches anything).

        This replaces the older `matches()` whose call direction was ambiguous.
        """
        levels = list(ScopeLevel)
        q_idx = levels.index(self.level)
        s_idx = levels.index(stored.level)
        # Stored narrower than query → invisible.
        if s_idx > q_idx:
            return False
        # Stored broader or equal → ids in stored must match caller ids.
        if stored.workspace_id is not None and stored.workspace_id != self.workspace_id:
            return False
        if stored.project_id is not None and stored.project_id != self.project_id:
            return False
        if stored.agent_id is not None and stored.agent_id != self.agent_id:
            return False
        return stored.session_id is None or stored.session_id == self.session_id

    # Kept as private back-compat shim for find_active_conflict until callers
    # migrate. New code must use can_read().
    def _matches_deprecated(self, other: MemoryScope) -> bool:
        return self.can_read(other)


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


class AgentAsset(BaseModel):
    """Stable logical identity for an agent, independent of a client install."""

    id: str
    name: str
    description: str | None = None
    role_tags: list[str] = Field(default_factory=list)
    default_sync_mode: SyncMode = SyncMode.MANUAL
    status: AgentAssetStatus = AgentAssetStatus.ACTIVE
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentEndpoint(BaseModel):
    """A concrete tool/client endpoint bound to an AgentAsset."""

    id: str
    asset_id: str
    client_id: str
    platform: EndpointPlatform
    display_name: str | None = None
    status: AgentAssetStatus = AgentAssetStatus.ACTIVE
    created_at: datetime = Field(default_factory=utcnow)


class Project(BaseModel):
    id: str
    name: str
    workspace_id: str | None = None
    description: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectMembership(BaseModel):
    asset_id: str
    project_id: str
    role: str | None = None
    sync_mode: SyncMode = SyncMode.MANUAL
    created_at: datetime = Field(default_factory=utcnow)


class MemoryGrant(BaseModel):
    """A reference to canonical memory, never a duplicated memory payload."""

    id: str
    memory_id: str
    asset_id: str
    sync_mode: SyncMode = SyncMode.MANUAL
    created_at: datetime = Field(default_factory=utcnow)


# Convenience: states that block a memory from default search results
VISIBLE_STATES = {MemoryState.ACTIVE}

# States considered terminal for default projections
TERMINAL_STATES = {MemoryState.SUPERSEDED, MemoryState.REVOKED}
