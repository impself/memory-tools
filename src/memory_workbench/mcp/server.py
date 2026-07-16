"""MCP server exposing memory_propose, memory_search, memory_get, memory_correct,
memory_forget, memory_explain.

Reuses the same domain service layer as HTTP. Runs as stdio transport.
Per spec §7: agents never directly issue approved/purged; revoke-only for
forget.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from memory_workbench.api.deps import session_dep
from memory_workbench.api.errors import to_mcp
from memory_workbench.domain import service
from memory_workbench.domain.models import (
    CallerContext,
    MemoryKind,
    MemoryScope,
    ScopeLevel,
)

mcp = FastMCP("memory-workbench")


def _scope_from_params(
    level: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> MemoryScope:
    return MemoryScope(
        level=ScopeLevel(level),
        workspace_id=workspace_id,
        project_id=project_id,
        agent_id=agent_id,
        session_id=session_id,
    )


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _err(exc: Exception) -> str:
    return json.dumps(to_mcp(exc))


# --- 6 MCP tools (spec §7) ----------------------------------------------


@mcp.tool()
def memory_propose(
    content: str,
    kind: str,
    level: str,
    client_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    subject: str | None = None,
    predicate: str | None = None,
    value: str | None = None,
    confidence: float | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> str:
    """Submit a candidate memory.

    kind: preference|fact|decision|constraint|procedure|experience
    level: global|workspace|project|agent|session
    Returns JSON {memory_id, state} on success, {error: {...}} on failure.
    """
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        ctx = CallerContext(client_id=client_id, agent_id=agent_id, scope=scope)
        inp = service.ProposeInput(
            content=content,
            kind=MemoryKind(kind),
            scope=scope,
            subject=subject,
            predicate=predicate,
            value=value,
            confidence=confidence,
            valid_from=valid_from,
            valid_until=valid_until,
        )
        try:
            rec = service.propose(sess, ctx, inp)
        except Exception as e:
            sess.rollback()
            return _err(e)
        sess.commit()
        return _ok(
            {
                "memory_id": rec.id,
                "state": rec.state.value,
                "supersedes_id": rec.supersedes_id,
            }
        )
    finally:
        sess.close()


@mcp.tool()
def memory_search(
    query: str,
    level: str,
    client_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Search active memories visible to the caller's scope.

    Scope filtering happens BEFORE substring match. A project-scoped caller
    sees only global + matching workspace + own project records.

    Returns JSON {results: [{memory_id, content, kind, subject, predicate,
    value, state, hit_reason}], trace_id}.
    """
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        ctx = CallerContext(client_id=client_id, agent_id=agent_id, scope=scope)
        kd = [MemoryKind(k) for k in kinds] if kinds else None
        try:
            results, trace = service.search(
                sess,
                ctx,
                query,
                kinds=kd,
                limit=limit,
            )
        except Exception as e:
            sess.rollback()
            return _err(e)
        sess.commit()
        return _ok(
            {
                "results": [
                    {
                        "memory_id": r.record.id,
                        "content": r.record.content,
                        "kind": r.record.kind.value,
                        "subject": r.record.subject,
                        "predicate": r.record.predicate,
                        "value": r.record.value,
                        "state": r.record.state.value,
                        "hit_reason": r.hit_reason,
                    }
                    for r in results
                ],
                "trace_id": trace.id,
            }
        )
    finally:
        sess.close()


@mcp.tool()
def memory_get(
    memory_id: str,
    level: str,
    client_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Get a memory's detail. Caller must be able to read the memory's scope."""
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        ctx = CallerContext(client_id=client_id, agent_id=agent_id, scope=scope)
        try:
            data = service.explain(sess, ctx, memory_id)
        except Exception as e:
            sess.rollback()
            return _err(e)
        sess.commit()
        return _ok(data)
    finally:
        sess.close()


@mcp.tool()
def memory_correct(
    memory_id: str,
    content: str,
    level: str,
    client_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    value: str | None = None,
) -> str:
    """Submit a corrected version. Old record superseded, new record active.

    Caller scope must be able to read the old record; new content is secret-scanned.
    """
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        ctx = CallerContext(client_id=client_id, agent_id=agent_id, scope=scope)
        inp = service.CorrectInput(memory_id=memory_id, content=content, value=value)
        try:
            rec = service.correct(sess, ctx, inp)
        except Exception as e:
            sess.rollback()
            return _err(e)
        sess.commit()
        return _ok(
            {
                "new_memory_id": rec.id,
                "old_memory_id": memory_id,
                "old_state": "superseded",
            }
        )
    finally:
        sess.close()


@mcp.tool()
def memory_forget(
    memory_id: str,
    level: str,
    client_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Logical revoke only. Hard purge is reserved for the local admin API.

    Spec §7: agents never directly issue purged events.
    """
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        # Caller must have read access before revoking — use explain for visibility check
        ctx = CallerContext(client_id=client_id, agent_id=agent_id, scope=scope)
        try:
            service.explain(sess, ctx, memory_id)  # raises if invisible
            rec = service.revoke(sess, memory_id, actor_id=client_id, reason=reason or "agent_forget")
        except Exception as e:
            sess.rollback()
            return _err(e)
        sess.commit()
        return _ok({"memory_id": memory_id, "state": rec.state.value})
    finally:
        sess.close()


@mcp.tool()
def memory_explain(
    memory_id: str,
    level: str,
    client_id: str,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Explain why a memory exists, its event timeline, and recent reads."""
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        ctx = CallerContext(client_id=client_id, agent_id=agent_id, scope=scope)
        try:
            data = service.explain(sess, ctx, memory_id)
        except Exception as e:
            sess.rollback()
            return _err(e)
        sess.commit()
        return _ok(data)
    finally:
        sess.close()


def run_stdio() -> None:
    """Entry point for `memory-workbench-mcp`."""
    mcp.run(transport="stdio")
