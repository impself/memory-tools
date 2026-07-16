"""HTTP routes mirroring MCP tools + admin endpoints for UI."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from memory_workbench.domain import service
from memory_workbench.domain.models import (
    CallerContext,
    MemoryKind,
    MemoryScope,
    MemoryState,
    ScopeLevel,
)
from memory_workbench.storage import repository as repo


# --- request/response schemas -------------------------------------------


class ScopeIn(BaseModel):
    level: ScopeLevel
    workspace_id: str | None = None
    project_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None

    def to_domain(self) -> MemoryScope:
        return MemoryScope(
            level=self.level,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
        )


class ProposeIn(BaseModel):
    content: str
    kind: MemoryKind
    scope: ScopeIn
    subject: str | None = None
    predicate: str | None = None
    value: str | None = None
    confidence: float | None = None
    auto_approve: bool = False
    client_id: str
    agent_id: str | None = None


class SearchIn(BaseModel):
    query: str = ""
    scope: ScopeIn
    kinds: list[MemoryKind] | None = None
    include_inactive: bool = False
    limit: int = 20
    client_id: str
    agent_id: str | None = None


class CorrectIn(BaseModel):
    content: str
    value: str | None = None
    client_id: str
    agent_id: str | None = None


class MemoryOut(BaseModel):
    id: str
    content: str
    kind: MemoryKind
    subject: str | None
    predicate: str | None
    value: str | None
    scope: ScopeIn
    state: MemoryState
    confidence: float | None
    sensitivity: str
    valid_from: datetime
    valid_until: datetime | None
    source_id: str
    supersedes_id: str | None
    created_at: datetime
    updated_at: datetime


class SearchHitOut(BaseModel):
    record: MemoryOut
    hit_reason: str


class SearchOut(BaseModel):
    results: list[SearchHitOut]
    trace_id: str
    elapsed_ms: int


class TraceOut(BaseModel):
    id: str
    timestamp: datetime
    client_id: str
    agent_id: str | None
    query: str
    scope: ScopeIn
    candidate_ids: list[str]
    returned_ids: list[str]
    hit_reasons: dict[str, str]
    elapsed_ms: int
    error: str | None


# --- router --------------------------------------------------------------


router = APIRouter(prefix="/api")


def _record_to_out(rec) -> MemoryOut:
    return MemoryOut(
        id=rec.id,
        content=rec.content,
        kind=rec.kind,
        subject=rec.subject,
        predicate=rec.predicate,
        value=rec.value,
        scope=ScopeIn(
            level=rec.scope.level,
            workspace_id=rec.scope.workspace_id,
            project_id=rec.scope.project_id,
            agent_id=rec.scope.agent_id,
            session_id=rec.scope.session_id,
        ),
        state=rec.state,
        confidence=rec.confidence,
        sensitivity=rec.sensitivity.value,
        valid_from=rec.valid_from,
        valid_until=rec.valid_until,
        source_id=rec.source_id,
        supersedes_id=rec.supersedes_id,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/memories")
def list_memories(
    state: Annotated[str | None, "filter by state"] = None,
    kind: Annotated[str | None, "filter by kind"] = None,
    limit: int = 200,
) -> list[MemoryOut]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        st = MemoryState(state) if state else None
        kd = MemoryKind(kind) if kind else None
        recs = repo.list_records(sess, state=st, kind=kd, limit=limit)
        return [_record_to_out(r) for r in recs]
    finally:
        sess.close()


@router.post("/memories")
def propose_memories(body: ProposeIn) -> MemoryOut:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        ctx = CallerContext(
            client_id=body.client_id,
            agent_id=body.agent_id,
            scope=body.scope.to_domain(),
        )
        inp = service.ProposeInput(
            content=body.content,
            kind=body.kind,
            scope=body.scope.to_domain(),
            subject=body.subject,
            predicate=body.predicate,
            value=body.value,
            confidence=body.confidence,
            auto_approve=body.auto_approve,
        )
        try:
            rec = service.propose(sess, ctx, inp)
        except ValueError as e:
            sess.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
        sess.commit()
        return _record_to_out(rec)
    finally:
        sess.close()


@router.post("/memories/search")
def search_memories(body: SearchIn) -> SearchOut:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        ctx = CallerContext(
            client_id=body.client_id,
            agent_id=body.agent_id,
            scope=body.scope.to_domain(),
        )
        results, trace = service.search(
            sess,
            ctx,
            body.query,
            kinds=body.kinds,
            include_inactive=body.include_inactive,
            limit=body.limit,
        )
        return SearchOut(
            results=[
                SearchHitOut(record=_record_to_out(r.record), hit_reason=r.hit_reason)
                for r in results
            ],
            trace_id=trace.id,
            elapsed_ms=trace.elapsed_ms,
        )
    finally:
        sess.close()


@router.post("/memories/{memory_id}/correct")
def correct_memory(memory_id: str, body: CorrectIn) -> MemoryOut:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        ctx = CallerContext(
            client_id=body.client_id,
            agent_id=body.agent_id,
            scope=MemoryScope(level=ScopeLevel.GLOBAL),
        )
        inp = service.CorrectInput(
            memory_id=memory_id,
            content=body.content,
            value=body.value,
        )
        try:
            rec = service.correct(sess, ctx, inp)
        except ValueError as e:
            sess.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
        sess.commit()
        return _record_to_out(rec)
    finally:
        sess.close()


@router.get("/memories/{memory_id}/explain")
def explain_memory(memory_id: str) -> dict:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        return service.explain(sess, memory_id)
    finally:
        sess.close()


@router.get("/traces")
def list_traces(limit: int = 50) -> list[TraceOut]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        traces = repo.list_traces(sess, limit=limit)
        return [
            TraceOut(
                id=t.id,
                timestamp=t.timestamp,
                client_id=t.client_id,
                agent_id=t.agent_id,
                query=t.query,
                scope=ScopeIn(
                    level=t.scope.level,
                    workspace_id=t.scope.workspace_id,
                    project_id=t.scope.project_id,
                    agent_id=t.scope.agent_id,
                    session_id=t.scope.session_id,
                ),
                candidate_ids=t.candidate_ids,
                returned_ids=t.returned_ids,
                hit_reasons=t.hit_reasons,
                elapsed_ms=t.elapsed_ms,
                error=t.error,
            )
            for t in traces
        ]
    finally:
        sess.close()
