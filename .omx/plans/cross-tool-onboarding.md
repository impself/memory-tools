# Cross-Tool MCP Onboarding Plan

Status: proposed
Date: 2026-07-19
Scope: make the existing AgentAsset memory-routing model usable from installed
Codex, Claude, and Cursor clients. Security Lab, remote service hosting,
automatic prompt injection, and delivery receipts remain out of scope.

## Requirements Summary

- Ship an installable `memory-workbench-mcp` stdio command. The server already
  exposes `run_stdio()` but `pyproject.toml` declares only
  `memory-workbench` (`src/memory_workbench/mcp/server.py:297`,
  `pyproject.toml:17`).
- Generate paste-ready MCP configuration for a bound `AgentEndpoint` instead
  of asking users to manually reconstruct command, environment, and client id.
- Bind a configured client to its endpoint server-side. Today `client_id` is a
  caller-provided MCP tool parameter (`mcp/server.py:58`, `115`), so a client
  can accidentally use the wrong asset even though endpoint routing already
  exists (`storage/repository.py:417`, `api/routes.py:501`).
- Show an honest endpoint status. A stdio MCP server cannot ping an IDE; status
  therefore means configured, recently observed, or stale based on persisted
  request activity, not a fabricated network-health signal.
- Preserve the current behaviour for unbound clients: scope-only search stays
  unchanged (`domain/service.py:489`, `api/routes.py:513`).

## Design Decisions

1. Treat an endpoint configuration as the authority for `client_id`.
   Generated configuration sets `MW_CLIENT_ID`; MCP tools resolve the caller
   from that environment. Keep `client_id` optional for backward compatibility
   during this milestone, but reject a supplied value that differs from an
   environment-bound endpoint id.
2. Render configuration; do not edit Cursor/Codex/Claude files automatically.
   The UI provides a copyable snippet and optional download. Writing arbitrary
   client configuration paths is a later, explicitly confirmed operation.
3. Implement status from a new endpoint-observation table or an endpoint
   activity projection populated by every successful MCP tool call. Store
   `last_seen_at`, `last_operation`, and a redacted error category; derive
   `configured`, `active` (seen within 24h), and `stale` statuses. Do not claim
   `healthy` merely because a local HTTP route is alive.
4. Add state in a new table rather than new columns on `agent_endpoints`, so
   the current `Base.metadata.create_all()` setup can upgrade existing local
   databases safely. Alembic remains a separate milestone.

## Implementation Steps

### 1. Formalize endpoint runtime identity

Files: `src/memory_workbench/mcp/server.py`,
`src/memory_workbench/domain/models.py`,
`src/memory_workbench/domain/errors.py`, `tests/test_mcp_contract.py`.

- Add a `McpRuntimeContext` resolver that reads `MW_CLIENT_ID` once per tool
  call and combines it with tool scope parameters.
- Change each MCP tool to use the runtime client id. Retain an optional
  compatibility parameter only until the next breaking release; reject a
  mismatching supplied id with a structured MCP validation error.
- Record a successful operation after propose, search, get, correct, forget,
  and explain. Do not write raw query text or memory content to the activity
  record.
- Ensure a missing `MW_CLIENT_ID` remains valid for the existing manual/dev
  flow and receives the current strict scope-only behaviour.

Acceptance:

- With `MW_CLIENT_ID=codex-local`, a tool call cannot claim `claude-local`.
- A bound client receives its AgentAsset effective set; an unbound client does
  not receive explicit grants outside its declared scope.
- All six MCP tools continue to return their current success/error JSON shapes.

### 2. Add packaged MCP command and configuration renderers

Files: `pyproject.toml`, `src/memory_workbench/mcp/entrypoint.py` (new),
`src/memory_workbench/mcp/config.py` (new), `tests/test_mcp_config.py` (new),
`Makefile`.

- Add `[project.scripts] memory-workbench-mcp =
  "memory_workbench.mcp.entrypoint:run"`; the entry point invokes the existing
  stdio server only and never starts FastAPI.
- Define typed `McpClientPlatform` and `McpLaunchProfile` values:
  `installed` uses `memory-workbench-mcp`; `repository` uses
  `uv --directory <absolute-repository-path> run memory-workbench-mcp`.
- Implement pure renderers for Codex, Claude, and Cursor that return a JSON
  object/snippet with a named server, command, arguments, and environment.
  Required environment: `MW_CLIENT_ID`; optional: absolute `MW_DB_PATH`.
- Keep platform-specific file locations out of the renderer. Display them in
  documentation only after verifying the current official client documentation
  at implementation time.
- Add `make mcp-check` to verify the installed command resolves and
  `make frontend-build` remains the UI build gate.

Acceptance:

- `uv run memory-workbench-mcp` starts stdio without starting Uvicorn.
- Every renderer produces valid JSON, includes the selected endpoint id, and
  never includes a secret or a relative database path.
- Snapshot tests cover all three platforms and both launch profiles.

### 3. Persist endpoint activity and expose setup/status APIs

Files: `src/memory_workbench/storage/tables.py`,
`src/memory_workbench/storage/repository.py`,
`src/memory_workbench/api/routes.py`, `tests/test_agent_assets.py`.

- Add `EndpointObservationRow` keyed by endpoint id. Upsert the latest
  activity with operation and timestamp; keep a bounded, redacted recent-error
  field only if an operation fails after context resolution.
- Add repository queries that resolve endpoint by client id, attach the newest
  observation, and compute `configured | active | stale | never_seen` without
  querying a client process.
- Extend `AssetDetailOut.endpoints` with status fields and add
  `GET /api/assets/{asset_id}/endpoints/{endpoint_id}/setup` to return a
  selected renderer payload. Validate that the endpoint belongs to the asset.
- Add `GET /api/assets/{asset_id}/endpoints/{endpoint_id}/status`; it returns
  the derived status, last seen time, last operation, and effective memory
  count. Do not add a fake "ping" endpoint.

Acceptance:

- A successful MCP search changes the matching endpoint from `never_seen` to
  `active` and updates the operation.
- One asset cannot read another asset's setup configuration or endpoint status.
- Existing databases initialize the new table on startup without data loss.

### 4. Build the endpoint setup wizard in the React UI

Files: `frontend/src/types.ts`, `frontend/src/api.ts`,
`frontend/src/main.tsx`, `frontend/src/styles.css`,
`frontend/src/__tests__/...` (new if Vitest is introduced).

- Replace the current single-line endpoint form (`frontend/src/main.tsx:65`)
  with an endpoint card: platform, stable client id, launch profile, status,
  last observed activity, and visible-memory count.
- Add a setup drawer/modal that requests the setup API, shows JSON safely as
  text, supports Copy, and offers download. Make clear that user approval is
  required before editing any IDE configuration.
- Display `never_seen`, `active`, and `stale` with explanatory wording rather
  than colour alone. Link the status to the last MCP operation and trace view.
- Keep existing asset/project/grant actions intact; do not make endpoint setup
  a prerequisite for creating or editing an AgentAsset.

Acceptance:

- At 375px and 1280px, a user can create an endpoint, copy a configuration,
  and distinguish a configured-but-never-used endpoint from an active one.
- The UI never renders configuration JSON through raw HTML or embeds it in an
  inline event handler.

### 5. Document, validate, and release the two-client path

Files: `README.md`, `docs/mcp-client-guide.md`, `docs/user-guide.md`,
`docs/technical-architecture.md`, `docs/status.md`, `docs/agent-assets.md`,
`Makefile`.

- Replace the current development-only MCP command in
  `docs/mcp-client-guide.md:9-12` with installed and repository-profile
  instructions plus a platform configuration example.
- Document endpoint status semantics, the 24-hour stale threshold, local-only
  security boundary, client-id mismatch rejection, and the fact that
  `automatic` grants remain delivery-eligible metadata rather than prompt
  injection.
- Add an end-to-end manual release checklist: Client A proposes/approves a
  project memory; Client B is bound to a different asset and receives only an
  explicit grant; revocation stops it; trace names the right asset.
- Run `make check`, `make mcp-check`, clean-install the package in a temporary
  environment, and perform the two-client checklist before release.

Acceptance:

- Documentation has no stale claim that MCP lacks a packaged entry point or
  that React/TypeScript is unimplemented.
- The release checklist can be completed from a fresh clone without invoking
  Python source code through `-c`.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| IDE configuration formats change | Verify official docs during implementation; isolate each renderer and snapshot it. |
| `client_id` can be spoofed by LLM tool arguments | Make `MW_CLIENT_ID` authoritative and reject mismatch. |
| Status appears more reliable than it is | Name it activity status; derive it only from successful observed calls. |
| Existing SQLite files fail after schema change | Add only a new table in this milestone; test startup against an existing schema fixture. |
| Configuration reveals a local path | Show it only in local UI/download; never place it in traces or server logs. |

## Verification Matrix

1. Unit: config renderers, runtime client-id resolver, status derivation, and
   redaction rules.
2. Integration: FastAPI setup/status APIs, authorization boundaries, successful
   MCP tool activity updates, grant/revoke retrieval behaviour.
3. Contract: packaged `memory-workbench-mcp` executable starts stdio and rejects
   conflicting environment/tool client ids.
4. Frontend: TypeScript build, responsive manual smoke test, safe JSON copy
   rendering, and no regression to asset/project/grant operations.
5. End-to-end: two distinct configured clients against one SQLite database;
   verify memory sharing, isolation, revocation, trace attribution, and stale
   status after a controlled timestamp fixture.

## Delivery Sequence

Commit 1: runtime identity + endpoint activity schema/repository + Python tests.
Commit 2: CLI entry point + pure config renderers + package/config tests.
Commit 3: setup/status HTTP API + React endpoint wizard + frontend build.
Commit 4: docs, Makefile targets, clean-install and two-client evidence.

## Out of Scope Follow-ups

- Per-endpoint `MemoryDelivery` acknowledgements, retry states, and prompt
  injection (requires a delivery contract rather than stdio retrieval).
- Automatic conflict case creation and a full version graph.
- Remote listener authentication, cloud synchronization, RBAC, and Security
  Lab integration.
