"""MCP server exposing memory_propose, memory_search, memory_get, memory_correct,
memory_forget, memory_explain.

Reuses the same domain service layer as HTTP. Runs as stdio transport.
Per spec §7: agents never directly issue approved/purged; revoke-only for
forget.

Cross-tool onboarding (plan §1): caller identity resolves from MW_CLIENT_ID
environment. Tool argument `client_id` is backward-compat only and must match
the env value when both are present. Each successful tool call records a
redacted endpoint observation so the UI can show activity status.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from memory_workbench.api.deps import session_dep
from memory_workbench.api.errors import to_mcp
from memory_workbench.domain import service
from memory_workbench.domain.errors import MemoryError
from memory_workbench.domain.models import (
    CallerContext,
    MemoryKind,
    MemoryScope,
    ScopeLevel,
)
from memory_workbench.mcp.runtime import resolve_client_id
from memory_workbench.storage import repository as repo

mcp = FastMCP("memory-workbench")


# --- shared helpers ------------------------------------------------------


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


def _record_activity(
    sess: Any,
    *,
    runtime_client_id: str,
    operation: str,
) -> None:
    """Record successful endpoint activity without storing request content.

    Skipped silently when the caller is unbound (no MW_CLIENT_ID and no
    argument) so the existing dev/manual flow is unaffected.
    """
    if not runtime_client_id:
        return
    endpoint = repo.get_endpoint_for_client_id(sess, runtime_client_id)
    if endpoint is None:
        return
    repo.record_endpoint_observation(
        sess,
        endpoint_id=endpoint.id,
        operation=operation,
    )


def _resolve_or_error(argument_client_id: str | None) -> tuple[str, str | None]:
    """Return (client_id, error_json_or_None).

    On ClientMismatch (env vs argument conflict) returns an error JSON string
    in slot 1 and an empty client_id. Otherwise returns the resolved id and
    None.
    """
    try:
        runtime = resolve_client_id(argument=argument_client_id)
    except MemoryError as exc:
        return "", _err(exc)
    return runtime.client_id, None


# --- 6 MCP tools (spec §7) ----------------------------------------------


@mcp.tool()
def memory_propose(
    content: str,
    kind: str,
    level: str,
    client_id: str | None = None,
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
    `client_id` is optional and only accepted for backward compatibility; the
    MW_CLIENT_ID environment variable is authoritative when set.

    Returns JSON {memory_id, state} on success, {error: {...}} on failure.
    """
    resolved, err = _resolve_or_error(client_id)
    if err:
        return err
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        asset = repo.get_asset_for_client_id(sess, resolved) if resolved else None
        ctx = CallerContext(
            client_id=resolved or client_id or "anonymous",
            agent_id=asset.id if asset else agent_id,
            scope=scope,
        )
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
        except Exception as exc:
            sess.rollback()
            return _err(exc)
        _record_activity(sess, runtime_client_id=resolved, operation="propose")
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
    client_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Search active memories visible to the caller's scope.

    Scope filtering happens BEFORE substring match. A project-scoped caller
    sees only global + matching workspace + own project records. When bound
    to an AgentAsset, the asset's effective set (memberships + grants)
    further restricts results.

    Returns JSON {results: [...], trace_id}.
    """
    resolved, err = _resolve_or_error(client_id)
    if err:
        return err
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        asset = repo.get_asset_for_client_id(sess, resolved) if resolved else None
        ctx = CallerContext(
            client_id=resolved or client_id or "anonymous",
            agent_id=asset.id if asset else agent_id,
            scope=scope,
        )
        kd = [MemoryKind(k) for k in kinds] if kinds else None
        records = repo.list_asset_visible_memories(sess, asset.id) if asset else None
        try:
            results, trace = service.search(
                sess,
                ctx,
                query,
                kinds=kd,
                limit=limit,
                records=records,
            )
        except Exception as exc:
            sess.rollback()
            return _err(exc)
        _record_activity(sess, runtime_client_id=resolved, operation="search")
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
    client_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Get a memory's detail. Caller must be able to read the memory's scope."""
    resolved, err = _resolve_or_error(client_id)
    if err:
        return err
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        asset = repo.get_asset_for_client_id(sess, resolved) if resolved else None
        ctx = CallerContext(
            client_id=resolved or client_id or "anonymous",
            agent_id=asset.id if asset else agent_id,
            scope=scope,
        )
        try:
            data = service.explain(sess, ctx, memory_id)
        except Exception as exc:
            sess.rollback()
            return _err(exc)
        _record_activity(sess, runtime_client_id=resolved, operation="get")
        sess.commit()
        return _ok(data)
    finally:
        sess.close()


@mcp.tool()
def memory_correct(
    memory_id: str,
    content: str,
    level: str,
    client_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    value: str | None = None,
) -> str:
    """Submit a corrected version. Old record superseded, new record active.

    Caller scope must be able to read the old record; new content is secret-scanned.
    """
    resolved, err = _resolve_or_error(client_id)
    if err:
        return err
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        asset = repo.get_asset_for_client_id(sess, resolved) if resolved else None
        ctx = CallerContext(
            client_id=resolved or client_id or "anonymous",
            agent_id=asset.id if asset else agent_id,
            scope=scope,
        )
        inp = service.CorrectInput(memory_id=memory_id, content=content, value=value)
        try:
            rec = service.correct(sess, ctx, inp)
        except Exception as exc:
            sess.rollback()
            return _err(exc)
        _record_activity(sess, runtime_client_id=resolved, operation="correct")
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
    client_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Logical revoke only. Hard purge is reserved for the local admin API.

    Spec §7: agents never directly issue purged events.
    """
    resolved, err = _resolve_or_error(client_id)
    if err:
        return err
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        asset = repo.get_asset_for_client_id(sess, resolved) if resolved else None
        ctx = CallerContext(
            client_id=resolved or client_id or "anonymous",
            agent_id=asset.id if asset else agent_id,
            scope=scope,
        )
        try:
            service.explain(sess, ctx, memory_id)  # raises if invisible
            rec = service.revoke(
                sess, memory_id,
                actor_id=resolved or client_id or "anonymous",
                reason=reason or "agent_forget",
            )
        except Exception as exc:
            sess.rollback()
            return _err(exc)
        _record_activity(sess, runtime_client_id=resolved, operation="forget")
        sess.commit()
        return _ok({"memory_id": memory_id, "state": rec.state.value})
    finally:
        sess.close()


@mcp.tool()
def memory_explain(
    memory_id: str,
    level: str,
    client_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Explain why a memory exists, its event timeline, and recent reads."""
    resolved, err = _resolve_or_error(client_id)
    if err:
        return err
    sess = session_dep()
    try:
        scope = _scope_from_params(level, workspace_id, project_id, agent_id, session_id)
        asset = repo.get_asset_for_client_id(sess, resolved) if resolved else None
        ctx = CallerContext(
            client_id=resolved or client_id or "anonymous",
            agent_id=asset.id if asset else agent_id,
            scope=scope,
        )
        try:
            data = service.explain(sess, ctx, memory_id)
        except Exception as exc:
            sess.rollback()
            return _err(exc)
        _record_activity(sess, runtime_client_id=resolved, operation="explain")
        sess.commit()
        return _ok(data)
    finally:
        sess.close()


def run_stdio() -> None:
    """Entry point for `memory-workbench-mcp`."""
    mcp.run(transport="stdio")
