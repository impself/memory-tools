# Memory Workbench

Local-first Agent Memory Control Plane. Event-ledger truth source, MCP-exposed, Web UI for management.

Status: runnable tracer-bullet. Core lifecycle, scope isolation, HTTP/MCP adapters,
retrieval traces and projection replay are implemented and tested. Not production-ready.

## Quick Start

```bash
uv sync
uv run memory-workbench
# → http://127.0.0.1:8000
```

First run creates `./memory_workbench.db` (SQLite). Bound to 127.0.0.1 only.

## Documentation

- [Documentation index](docs/README.md)
- [Current status and roadmap](docs/status.md)
- [User guide](docs/user-guide.md)
- [MCP client guide](docs/mcp-client-guide.md)
- [Technical architecture](docs/technical-architecture.md)
- [MVP specification](docs/spec.md)
- [Documentation maintenance](docs/maintenance.md)

## Tracer-bullet chain (spec §17)

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
  storage/       # SQLite event log + projection
  api/           # FastAPI HTTP routes
  mcp/           # MCP tools (propose, search, correct)
  tracing/       # RetrievalTrace recorder
  static/        # minimal Web UI
  main.py        # uvicorn entry
tests/
  test_tracer.py       # end-to-end chain test
  test_api.py          # HTTP integration and UI security contracts
  test_mcp_contract.py # MCP privilege boundary
docs/                  # product, technical and usage documentation
```

## Current limitations

- Search is deterministic substring matching, not FTS5 yet.
- The Web UI is bundled HTML/JavaScript, not the target React/TypeScript app.
- MCP tools exist, but a packaged `memory-workbench-mcp` entry point is not available yet.
- Database initialization uses `create_all`; Alembic migrations are not implemented yet.

See [docs/status.md](docs/status.md) for the maintained progress report.
