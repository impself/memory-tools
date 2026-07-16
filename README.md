# Memory Workbench

Local-first Agent Memory Control Plane. Event-ledger truth source, MCP-exposed, Web UI for management.

Status: tracer-bullet (end-to-end thin slice per spec §17). Not production-ready.

## Quick Start

```bash
uv sync
uv run memory-workbench
# → http://127.0.0.1:8000
```

First run creates `./memory_workbench.db` (SQLite). Bound to 127.0.0.1 only.

## Tracer-bullet chain (spec §17)

1. Start service
2. Client A `memory_propose` → SQLite logs event → projection visible
3. Web UI lists memory
4. Client B `memory_search` (same project scope) → returns memory → Trace row written
5. User `memory_correct` → new event + new version, old `superseded`
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
  test_tracer.py # end-to-end chain test
```

See `CLAUDE.md` for full spec context, `docs/spec.md` (when added) for PRD v0.1.
