# Memory Workbench

Local-first Agent Memory Control Plane. Event-ledger truth source, MCP-exposed, Web UI for management.

Status: cross-tool onboarding milestone. Core lifecycle, scope isolation,
HTTP/MCP adapters, retrieval traces, projection replay, AgentAsset routing,
packaged `memory-workbench-mcp`, and endpoint activity status are implemented
and tested. Not production-ready.

## Quick Start

```bash
uv sync
uv run memory-workbench
# → http://127.0.0.1:8000
```

First run creates `./memory_workbench.db` (SQLite). Bound to 127.0.0.1 only.

## MCP for installed clients

```bash
uv tool install memory-workbench
memory-workbench-mcp                          # stdio server only
```

Configure each MCP client (Codex / Claude / Cursor) via the Web UI: create
an AgentAsset, add an endpoint, then click **生成配置** to copy or download
the paste-ready JSON. The client's authoritative identity comes from
`MW_CLIENT_ID`; tool-argument `client_id` must match it when both are set.

## Documentation

- [Documentation index](docs/README.md)
- [Current status and roadmap](docs/status.md)
- [User guide](docs/user-guide.md)
- [MCP client guide](docs/mcp-client-guide.md)
- [Technical architecture](docs/technical-architecture.md)
- [MVP specification](docs/spec.md)
- [Documentation maintenance](docs/maintenance.md)
- [Agent assets and memory routing](docs/agent-assets.md)

## Tracer-bullet chain

1. Start service
2. Client A `memory_propose` → SQLite logs candidate event → projection visible
3. User reviews and approves the candidate in the Web UI
4. Client B `memory_search` (same project scope) → returns memory → Trace row written
5. User or Client A `memory_correct` → new event + version, old `superseded`
6. Client B re-searches → reads new value; old one excluded

## Layout

```
src/memory_workbench/
  domain/        # models, state machine, service
  storage/       # SQLite event log + projection + endpoint observations
  api/           # FastAPI HTTP routes
  mcp/           # MCP tools + runtime identity + config renderers + entrypoint
  tracing/       # RetrievalTrace recorder
  static/        # production build output for the Web UI
  main.py        # uvicorn entry
frontend/        # React + TypeScript + Vite management UI
tests/           # pytest (domain, api, mcp contract, agent assets, endpoint setup)
docs/            # product, technical and usage documentation
```

## Current limitations

- Search is deterministic substring matching, not FTS5 yet.
- The React + TypeScript UI must be built with `cd frontend && npm run build`
  before FastAPI serves the latest production bundle.
- Database initialization uses `create_all`; Alembic migrations are not implemented yet.
- Endpoint status derives from local MCP observations only — no network ping.

See [docs/status.md](docs/status.md) for the maintained progress report.

## Development commands

```bash
make install          # uv sync --extra dev
make check            # test + lint + typecheck + frontend build
make mcp-check        # verify memory-workbench-mcp console script is registered
make mcp              # run the stdio MCP server locally
make release-checklist # print the manual two-client release steps
```
