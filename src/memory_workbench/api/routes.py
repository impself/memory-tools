"""HTTP routes mirroring MCP tools + admin endpoints for UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from memory_workbench.api.errors import to_http
from memory_workbench.domain import service
from memory_workbench.domain.errors import ValidationError
from memory_workbench.domain.models import (
    AgentAsset,
    AgentEndpoint,
    CallerContext,
    EndpointPlatform,
    EndpointStatus,
    MemoryGrant,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryState,
    Project,
    ProjectMembership,
    ScopeLevel,
    SyncMode,
)
from memory_workbench.mcp.config import RenderInputs, render
from memory_workbench.storage import repository as repo

# --- request/response schemas -------------------------------------------


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeIn(StrictRequest):
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


class ExplainContextIn(ScopeIn):
    client_id: str

    def to_context(self) -> CallerContext:
        return CallerContext(
            client_id=self.client_id,
            agent_id=self.agent_id,
            scope=self.to_domain(),
        )


class ProposeIn(StrictRequest):
    content: str
    kind: MemoryKind
    scope: ScopeIn
    subject: str | None = None
    predicate: str | None = None
    value: str | None = None
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    client_id: str
    agent_id: str | None = None


class SearchIn(StrictRequest):
    query: str = ""
    scope: ScopeIn
    kinds: list[MemoryKind] | None = None
    limit: int = Field(default=20, ge=1, le=200)
    client_id: str
    agent_id: str | None = None


class CorrectIn(StrictRequest):
    content: str
    value: str | None = None
    client_id: str
    agent_id: str | None = None
    scope: ScopeIn


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


class CreateAssetIn(StrictRequest):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    role_tags: list[str] = Field(default_factory=list, max_length=20)
    default_sync_mode: SyncMode = SyncMode.MANUAL


class CreateProjectIn(StrictRequest):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=4000)


class AddEndpointIn(StrictRequest):
    client_id: str = Field(min_length=1, max_length=128)
    platform: EndpointPlatform
    display_name: str | None = Field(default=None, max_length=128)


class AddMembershipIn(StrictRequest):
    project_id: str = Field(min_length=1, max_length=128)
    role: str | None = Field(default=None, max_length=128)
    sync_mode: SyncMode = SyncMode.MANUAL


class AddMemoryGrantIn(StrictRequest):
    memory_id: str = Field(min_length=1, max_length=64)
    sync_mode: SyncMode = SyncMode.MANUAL


class EndpointStatusOut(BaseModel):
    """Activity-derived endpoint status payload."""

    endpoint_id: str
    asset_id: str
    client_id: str
    platform: EndpointPlatform
    status: EndpointStatus
    last_seen_at: datetime | None
    last_operation: str | None
    last_error_category: str | None
    visible_memory_count: int


class EndpointSetupIn(StrictRequest):
    """Body for POST /endpoints/{id}/setup. Optional path overrides."""

    profile: Literal["installed", "repository"] = "installed"
    repository_path: str | None = None
    db_path: str | None = None


class EndpointSetupOut(BaseModel):
    endpoint_id: str
    client_id: str
    platform: EndpointPlatform
    profile: Literal["installed", "repository"]
    config: dict[str, Any]


class AssetDetailOut(AgentAsset):
    endpoints: list[EndpointStatusOut]
    projects: list[ProjectMembership]
    grants: list[MemoryGrant]
    memories: list[MemoryOut]
    memory_count: int


# --- router --------------------------------------------------------------


router = APIRouter(prefix="/api")


def _record_to_out(rec: MemoryRecord) -> MemoryOut:
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


def _asset_detail(session: Any, asset: AgentAsset) -> AssetDetailOut:
    memories = repo.list_asset_visible_memories(session, asset.id)
    endpoints = [
        _endpoint_status_out(session, e) for e in repo.list_asset_endpoints(session, asset.id)
    ]
    return AssetDetailOut(
        **asset.model_dump(),
        endpoints=endpoints,
        projects=repo.list_asset_memberships(session, asset.id),
        grants=repo.list_asset_grants(session, asset.id),
        memories=[_record_to_out(memory) for memory in memories],
        memory_count=len(memories),
    )


def _require_asset(session: Any, asset_id: str) -> AgentAsset:
    asset = repo.get_agent_asset(session, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"agent asset {asset_id} not found")
    return asset


def _endpoint_status_out(session: Any, endpoint: AgentEndpoint) -> EndpointStatusOut:
    status = repo.derive_endpoint_status(session, endpoint.id)
    obs = repo.get_endpoint_observation(session, endpoint.id)
    memories = repo.list_asset_visible_memories(session, endpoint.asset_id)
    return EndpointStatusOut(
        endpoint_id=endpoint.id,
        asset_id=endpoint.asset_id,
        client_id=endpoint.client_id,
        platform=endpoint.platform,
        status=status,
        last_seen_at=obs.last_seen_at if obs else None,
        last_operation=obs.last_operation if obs else None,
        last_error_category=obs.last_error_category if obs else None,
        visible_memory_count=len(memories),
    )


def _require_endpoint(session: Any, asset_id: str, endpoint_id: str) -> AgentEndpoint:
    endpoint = repo.get_endpoint(session, endpoint_id)
    if endpoint is None or endpoint.asset_id != asset_id:
        raise HTTPException(
            status_code=404,
            detail=f"endpoint {endpoint_id} not found on asset {asset_id}",
        )
    return endpoint


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/assets")
def list_assets() -> list[AssetDetailOut]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        return [_asset_detail(sess, asset) for asset in repo.list_agent_assets(sess)]
    finally:
        sess.close()


@router.post("/assets")
def create_asset(body: CreateAssetIn) -> AgentAsset:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        asset = repo.create_agent_asset(
            sess,
            name=body.name,
            description=body.description,
            role_tags=body.role_tags,
            default_sync_mode=body.default_sync_mode,
        )
        sess.commit()
        return asset
    finally:
        sess.close()


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str) -> AssetDetailOut:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        return _asset_detail(sess, _require_asset(sess, asset_id))
    finally:
        sess.close()


@router.post("/assets/{asset_id}/endpoints")
def add_asset_endpoint(asset_id: str, body: AddEndpointIn) -> AgentEndpoint:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        _require_asset(sess, asset_id)
        endpoint = repo.add_agent_endpoint(
            sess,
            asset_id=asset_id,
            client_id=body.client_id,
            platform=body.platform,
            display_name=body.display_name,
        )
        try:
            sess.commit()
        except IntegrityError as exc:
            sess.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"client_id {body.client_id!r} is already bound to an agent asset",
            ) from exc
        return endpoint
    finally:
        sess.close()


@router.get("/assets/{asset_id}/endpoints/{endpoint_id}/status")
def get_endpoint_status(asset_id: str, endpoint_id: str) -> EndpointStatusOut:
    """Activity-derived status. Never pings the client process.

    Returns never_seen | active | stale based on the latest recorded
    observation, plus the redacted last operation and effective memory count.
    """
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        endpoint = _require_endpoint(sess, asset_id, endpoint_id)
        return _endpoint_status_out(sess, endpoint)
    finally:
        sess.close()


@router.post("/assets/{asset_id}/endpoints/{endpoint_id}/setup")
def render_endpoint_setup(
    asset_id: str, endpoint_id: str, body: EndpointSetupIn
) -> EndpointSetupOut:
    """Render paste-ready MCP configuration for this endpoint.

    The response is plain JSON. The UI shows it as text and offers Copy/Download;
    no automatic writes to client config files.
    """
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        endpoint = _require_endpoint(sess, asset_id, endpoint_id)
        try:
            repo_path_arg = Path(body.repository_path) if body.repository_path else None
            db_path_arg = Path(body.db_path) if body.db_path else None
            # Reject relative inputs before resolve() silently absolutizes them.
            if repo_path_arg is not None and not repo_path_arg.is_absolute():
                raise ValidationError("repository_path must be absolute")
            if db_path_arg is not None and not db_path_arg.is_absolute():
                raise ValidationError("db_path must be absolute")
            inputs = RenderInputs(
                client_id=endpoint.client_id,
                platform=endpoint.platform,
                profile=body.profile,
                repository_path=repo_path_arg,
                db_path=db_path_arg,
            )
            payload = render(endpoint.platform, inputs)
        except ValidationError as exc:
            raise to_http(exc) from exc
        return EndpointSetupOut(
            endpoint_id=endpoint.id,
            client_id=endpoint.client_id,
            platform=endpoint.platform,
            profile=body.profile,
            config=payload,
        )
    finally:
        sess.close()


@router.post("/assets/{asset_id}/projects")
def add_asset_project(asset_id: str, body: AddMembershipIn) -> ProjectMembership:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        _require_asset(sess, asset_id)
        if repo.get_project(sess, body.project_id) is None:
            raise HTTPException(status_code=404, detail=f"project {body.project_id} not found")
        membership = repo.add_project_membership(
            sess,
            asset_id=asset_id,
            project_id=body.project_id,
            role=body.role,
            sync_mode=body.sync_mode,
        )
        try:
            sess.commit()
        except IntegrityError as exc:
            sess.rollback()
            raise HTTPException(status_code=409, detail="asset is already a project member") from exc
        return membership
    finally:
        sess.close()


@router.post("/assets/{asset_id}/grants")
def add_asset_memory_grant(asset_id: str, body: AddMemoryGrantIn) -> MemoryGrant:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        _require_asset(sess, asset_id)
        memory = repo.get_record(sess, body.memory_id)
        if memory is None:
            raise HTTPException(status_code=404, detail=f"memory {body.memory_id} not found")
        if memory.state != MemoryState.ACTIVE:
            raise HTTPException(status_code=409, detail="only active memories can be granted")
        grant = repo.add_memory_grant(
            sess,
            asset_id=asset_id,
            memory_id=body.memory_id,
            sync_mode=body.sync_mode,
        )
        try:
            sess.commit()
        except IntegrityError as exc:
            sess.rollback()
            raise HTTPException(status_code=409, detail="memory is already granted to this asset") from exc
        return grant
    finally:
        sess.close()


@router.delete("/assets/{asset_id}/grants/{memory_id}")
def remove_asset_memory_grant(asset_id: str, memory_id: str) -> dict[str, str]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        _require_asset(sess, asset_id)
        if not repo.remove_memory_grant(sess, asset_id=asset_id, memory_id=memory_id):
            raise HTTPException(status_code=404, detail="memory grant not found")
        sess.commit()
        return {"memory_id": memory_id, "status": "revoked"}
    finally:
        sess.close()


@router.get("/assets/{asset_id}/memories")
def list_asset_memories(asset_id: str) -> list[MemoryOut]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        _require_asset(sess, asset_id)
        return [_record_to_out(memory) for memory in repo.list_asset_visible_memories(sess, asset_id)]
    finally:
        sess.close()


@router.get("/projects")
def list_projects() -> list[Project]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        return repo.list_projects(sess)
    finally:
        sess.close()


@router.post("/projects")
def create_project(body: CreateProjectIn) -> Project:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        if repo.get_project(sess, body.id) is not None:
            raise HTTPException(status_code=409, detail=f"project {body.id} already exists")
        project = repo.create_project(
            sess,
            project_id=body.id,
            name=body.name,
            workspace_id=body.workspace_id,
            description=body.description,
        )
        sess.commit()
        return project
    finally:
        sess.close()


@router.get("/projects/{project_id}/assets")
def list_project_assets(project_id: str) -> list[ProjectMembership]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        if repo.get_project(sess, project_id) is None:
            raise HTTPException(status_code=404, detail=f"project {project_id} not found")
        return repo.list_project_memberships(sess, project_id)
    finally:
        sess.close()


@router.get("/projects/{project_id}/memories")
def list_project_memories(project_id: str) -> list[MemoryOut]:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        if repo.get_project(sess, project_id) is None:
            raise HTTPException(status_code=404, detail=f"project {project_id} not found")
        return [_record_to_out(memory) for memory in repo.list_project_active_memories(sess, project_id)]
    finally:
        sess.close()


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
    from memory_workbench.api.errors import to_http

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
            valid_from=body.valid_from,
            valid_until=body.valid_until,
        )
        try:
            rec = service.propose(sess, ctx, inp)
        except Exception as e:
            sess.rollback()
            raise to_http(e) from e
        sess.commit()
        return _record_to_out(rec)
    finally:
        sess.close()


@router.post("/memories/search")
def search_memories(body: SearchIn) -> SearchOut:
    from memory_workbench.api.deps import session_dep

    sess = session_dep()
    try:
        asset = repo.get_asset_for_client_id(sess, body.client_id)
        ctx = CallerContext(
            client_id=body.client_id,
            agent_id=asset.id if asset else body.agent_id,
            scope=body.scope.to_domain(),
        )
        results, trace = service.search(
            sess,
            ctx,
            body.query,
            kinds=body.kinds,
            limit=body.limit,
            records=repo.list_asset_visible_memories(sess, asset.id) if asset else None,
        )
        sess.commit()
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
    from memory_workbench.api.errors import to_http

    sess = session_dep()
    try:
        ctx = CallerContext(
            client_id=body.client_id,
            agent_id=body.agent_id,
            scope=body.scope.to_domain(),
        )
        inp = service.CorrectInput(
            memory_id=memory_id,
            content=body.content,
            value=body.value,
        )
        try:
            rec = service.correct(sess, ctx, inp)
        except Exception as e:
            sess.rollback()
            raise to_http(e) from e
        sess.commit()
        return _record_to_out(rec)
    finally:
        sess.close()


@router.get("/memories/{memory_id}/explain")
def explain_memory(
    memory_id: str,
    context: Annotated[ExplainContextIn, Query()],
) -> dict[str, Any]:
    from memory_workbench.api.deps import session_dep
    from memory_workbench.api.errors import to_http

    sess = session_dep()
    try:
        try:
            return service.explain(sess, context.to_context(), memory_id)
        except Exception as e:
            raise to_http(e) from e
    finally:
        sess.close()


class LifecycleIn(StrictRequest):
    reason: str | None = None


@router.post("/memories/{memory_id}/approve")
def approve_memory(memory_id: str, body: LifecycleIn) -> MemoryOut:
    from memory_workbench.api.deps import session_dep
    from memory_workbench.api.errors import to_http

    sess = session_dep()
    try:
        try:
            rec = service.approve(sess, memory_id, actor_id="web-ui")
        except Exception as e:
            sess.rollback()
            raise to_http(e) from e
        sess.commit()
        return _record_to_out(rec)
    finally:
        sess.close()


@router.post("/memories/{memory_id}/quarantine")
def quarantine_memory(memory_id: str, body: LifecycleIn) -> MemoryOut:
    from memory_workbench.api.deps import session_dep
    from memory_workbench.api.errors import to_http

    sess = session_dep()
    try:
        try:
            rec = service.quarantine(sess, memory_id, actor_id="web-ui", reason=body.reason)
        except Exception as e:
            sess.rollback()
            raise to_http(e) from e
        sess.commit()
        return _record_to_out(rec)
    finally:
        sess.close()


@router.post("/memories/{memory_id}/revoke")
def revoke_memory(memory_id: str, body: LifecycleIn) -> MemoryOut:
    from memory_workbench.api.deps import session_dep
    from memory_workbench.api.errors import to_http

    sess = session_dep()
    try:
        try:
            rec = service.revoke(sess, memory_id, actor_id="web-ui", reason=body.reason)
        except Exception as e:
            sess.rollback()
            raise to_http(e) from e
        sess.commit()
        return _record_to_out(rec)
    finally:
        sess.close()


@router.post("/memories/{memory_id}/purge")
def purge_memory(memory_id: str, body: LifecycleIn) -> dict[str, Any]:
    """Hard delete. Spec §10: scrub content + projection; tombstone remains."""
    from memory_workbench.api.deps import session_dep
    from memory_workbench.api.errors import to_http

    sess = session_dep()
    try:
        try:
            service.purge(sess, memory_id, actor_id="web-ui")
        except Exception as e:
            sess.rollback()
            raise to_http(e) from e
        sess.commit()
        return {"memory_id": memory_id, "purged": True}
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
