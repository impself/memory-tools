# Agent Assets

> Document status: Active
> Last verified: 2026-07-16
> Applies to: 0.1.x AgentAsset slice

## Purpose

This slice introduces the first management surface for multi-agent work. The
user first creates a stable AgentAsset, then connects it to projects and tool
endpoints. The asset's memory panel shows its effective memory set and allows
the user to explicitly grant selected active memories.

## Model

```text
AgentAsset 1 --- N AgentEndpoint
AgentAsset N --- N Project (ProjectMembership)
AgentAsset N --- N MemoryRecord (MemoryGrant)
```

`AgentAsset` is not the same thing as a Codex, Claude, or Cursor process.
Those installations are endpoints. A client id can bind to only one asset.

Memory visibility is calculated, not copied:

```text
active global memories
+ active matching project/workspace memories
+ active memories scoped to the asset itself
+ active explicit grants
```

Expired, candidate, quarantined, revoked, superseded, and purged records are
not in the effective memory set. A grant is a durable reference to canonical
memory, so a later correction or revocation is immediately consistent for all
assets.

## Web workflow

1. Start the Python API: `uv run memory-workbench`.
2. In another terminal, enter `frontend`, install dependencies, and run
   `npm run dev`. Open the Vite URL it prints for development; its `/api`
   requests proxy to the local Python service.
3. Create an AgentAsset from the left column.
4. Create or associate a Project in the middle column. Click a project to
   narrow the memory panel to that project's active memories.
5. Bind a Codex, Claude, Cursor, or custom endpoint with its `client_id`.
   Searches from a bound client resolve to the asset's effective memory set;
   unbound clients keep the existing strict scope-only search behaviour.
6. Review active canonical memories in the right column. "Grant" creates a
   reference and "Revoke" removes it; neither action creates a cloned memory.
   Manual means an explicitly selected route. Automatic marks the grant as
   delivery-eligible metadata; physical prompt injection/delivery receipts are
   intentionally deferred, so both modes are searchable after being granted.
7. "Correct" creates a new canonical version and supersedes the old one.
6. Run `npm run build` before serving the production UI from FastAPI. The build
   output is `src/memory_workbench/static` and the Python root route serves it.

## HTTP API

- `GET` / `POST` `/api/assets`
- `GET` `/api/assets/{asset_id}`
- `POST` `/api/assets/{asset_id}/endpoints`
- `POST` `/api/assets/{asset_id}/projects`
- `GET` `/api/assets/{asset_id}/memories`
- `POST` / `DELETE` `/api/assets/{asset_id}/grants`
- `GET` / `POST` `/api/projects`
- `GET` `/api/projects/{project_id}/assets`

The current endpoints are local-admin endpoints. They are intentionally not an
agent self-service permission API.

## Explicitly deferred

- Endpoint registration directly from MCP client configuration
- Per-endpoint delivery acknowledgements and stale/failed delivery state
- Automatic conflict case creation and resolution UI
- Memory version graph and retrieval-to-agent-run causal evidence
- Security Lab integration
