"""MCP server exposing memory_propose, memory_search, memory_correct.

Reuses the same domain service layer as HTTP. Runs as stdio transport
(the simplest path for Codex / Claude Desktop / Cursor to spawn it).
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from memory_workbench.api.deps import session_dep
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
    auto_approve: bool = False,
) -> str:
    """Submit a candidate memory.

    kind: preference|fact|decision|constraint|procedure|experience
    level: global|workspace|project|agent|session
    auto_approve: set true for low-risk project conventions (active immediately)
    Returns: JSON {memory_id, state}.
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
            auto_approve=auto_approve,
        )
        try:
            rec = service.propose(sess, ctx, inp)
        except ValueError as e:
            sess.rollback()
            return json.dumps({"error": str(e)})
        sess.commit()
        return json.dumps(
            {"memory_id": rec.id, "state": rec.state.value, "supersedes_id": rec.supersedes_id}
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
    include_inactive: bool = False,
    limit: int = 20,
) -> str:
    """Search active memories within a scope.

    Returns JSON {results: [{memory_id, content, kind, subject, predicate, value,
    scope, state, hit_reason}], trace_id}.
    """
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        ctx = CallerContext(client_id=client_id, agent_id=agent_id, scope=scope)
        kd = [MemoryKind(k) for k in kinds] if kinds else None
        results, trace = service.search(
            sess,
            ctx,
            query,
            kinds=kd,
            include_inactive=include_inactive,
            limit=limit,
        )
        return json.dumps(
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
def memory_correct(
    memory_id: str,
    content: str,
    client_id: str,
    value: str | None = None,
    agent_id: str | None = None,
) -> str:
    """Submit a corrected version. Old record superseded, new record active.

    Returns JSON {new_memory_id, old_memory_id, old_state}.
    """
    sess = session_dep()
    try:
        ctx = CallerContext(
            client_id=client_id,
            agent_id=agent_id,
            scope=MemoryScope(level=ScopeLevel.GLOBAL),
        )
        inp = service.CorrectInput(
            memory_id=memory_id,
            content=content,
            value=value,
        )
        try:
            rec = service.correct(sess, ctx, inp)
        except ValueError as e:
            sess.rollback()
            return json.dumps({"error": str(e)})
        sess.commit()
        return json.dumps(
            {
                "new_memory_id": rec.id,
                "old_memory_id": memory_id,
                "old_state": "superseded",
            }
        )
    finally:
        sess.close()


def run_stdio() -> None:
    """Entry point for `memory-workbench-mcp`."""
    mcp.run(transport="stdio")
