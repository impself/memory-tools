"""SQLAlchemy tables for events, projection, traces.

Tracer-bullet uses create_all. Production adds Alembic. Spec §6 schema.

Scope stored as JSON-encoded dict. Pydantic models parse it back on read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "memory_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(String(128))
    source_id: Mapped[str] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    previous_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MemoryRow(Base):
    """Current projection of a memory."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    predicate: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(16), default="normal")
    valid_from: Mapped[datetime] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_id: Mapped[str] = mapped_column(String(128))
    supersedes_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TraceRow(Base):
    __tablename__ = "retrieval_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    client_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    query: Mapped[str] = mapped_column(Text)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    candidate_ids: Mapped[list[str]] = mapped_column(JSON)
    returned_ids: Mapped[list[str]] = mapped_column(JSON)
    hit_reasons: Mapped[dict[str, str]] = mapped_column(JSON)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentAssetRow(Base):
    __tablename__ = "agent_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_tags: Mapped[list[str]] = mapped_column(JSON)
    default_sync_mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AgentEndpointRow(Base):
    __tablename__ = "agent_endpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(64), index=True)
    client_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ProjectMembershipRow(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("asset_id", "project_id", name="uq_asset_project"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sync_mode: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class MemoryGrantRow(Base):
    __tablename__ = "memory_grants"
    __table_args__ = (UniqueConstraint("memory_id", "asset_id", name="uq_memory_asset_grant"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(64), index=True)
    asset_id: Mapped[str] = mapped_column(String(64), index=True)
    sync_mode: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime)


# Helpful indexes for common searches
Index("ix_memories_state_kind", MemoryRow.state, MemoryRow.kind)
Index("ix_memories_subject_predicate", MemoryRow.subject, MemoryRow.predicate)
