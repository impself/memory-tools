# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Memory Workbench** — local-first Agent Memory Control Plane. Event-ledger truth source, MCP-exposed to multiple AI clients (Codex, Claude, Cursor), Web UI for management.

Core differentiator: memory is not silently overwritten text — it is a change record with source, scope, state, and version. Every retrieval is traceable.

Status: pre-implementation. Spec frozen at v0.1 (2026-07-16).

## Architecture (Big Picture)

Three concentric layers:

1. **Event ledger (immutable)** — `MemoryEvent` rows in SQLite. Original facts never mutate. Current `MemoryRecord` view is folded from events.
2. **Domain services** — state machine (`candidate → active → superseded/quarantined/revoked`), scope filtering, conflict matching, retrieval pipeline.
3. **Two fronts sharing one domain** — FastAPI HTTP + official MCP Python SDK (same domain services), React/Vite Web UI.

### Write flow
```
MCP/HTTP input
  → Schema validate
  → Sensitivity scan
  → Scope normalize
  → Deterministic dup/conflict match (subject+predicate+scope key)
  → Append immutable event
  → Tx: update MemoryRecord projection + FTS5
  → Return candidate or active record
```

### Read flow
```
Query + caller context
  → Scope + state filter (BEFORE ranking)
  → FTS5 candidates
  → Optional embedding candidates
  → Merge + stable sort
  → Token/count budget trim
  → Write RetrievalTrace
  → Return with explanation fields
```

Critical invariant: **scope filtering happens before full-text or vector ranking.** Project constraints must not leak across projects regardless of semantic similarity.

## Tech Stack

- **Backend**: Python 3.12+, `uv` for env/deps, FastAPI + Uvicorn, Pydantic v2, SQLAlchemy 2 + Alembic + SQLite (FTS5), official MCP Python SDK, structlog.
- **Frontend**: TypeScript strict, React + Vite (no Next.js — no SSR need), `openapi-typescript` or Orval generated from backend OpenAPI schema.
- **Tests**: pytest (backend), Vitest (frontend unit), Playwright (E2E).
- **Distribution**: FastAPI serves Vite static build in production — single Python process, no Node runtime required for end users.

## Layout (target)

```
backend/
  pyproject.toml
  src/memory_workbench/
    api/            # FastAPI routes + OpenAPI
    domain/         # models, state machine, policies, errors
    storage/        # event store, projections, FTS5, repos
    mcp/            # MCP tools + client context mapping
    tracing/        # RetrievalTrace + redaction
    import_export/  # JSONL + compat checks
    main.py         # local service + static frontend entry
  migrations/       # Alembic
  tests/
frontend/
  src/
  src/generated/    # auto-gen from OpenAPI — DO NOT hand-edit
  tests/
docs/
  getting-started.md
  mcp-clients/
```

## Domain Model Quick Reference

### MemoryRecord (queryable projection)
Fields: `id, content, kind, subject?, predicate?, value?, scope, state, confidence?, sensitivity, validFrom, validUntil?, sourceId, supersedesId?, createdAt, updatedAt`.

`MemoryKind`: `preference | fact | decision | constraint | procedure | experience`

`MemoryState`: `candidate | active | superseded | quarantined | revoked`

`MemoryScope.level`: `global | workspace | project | agent | session` + optional ids.

`MemorySensitivity`: `normal | private | secret`

**Conflict key**: `subject + predicate + scope`. Free-text without structured keys → only "possible duplicate" hint, never auto-supersede.

### MemoryEvent (immutable)
Types: `memory.proposed | approved | corrected | superseded | quarantined | revoked | purged | retrieved | exported`

Required: `event_id, memory_id, event_type, actor_type, actor_id, source_id, timestamp, payload, previous_event_id`.

`purged` is special: deletes content + index, leaves contentless tombstone to prevent resurrection on import/sync.

### RetrievalTrace
One per `memory_search` call. Records: caller client/agent id, query, filters, token budget, scope-filtered candidates, ranking signals, final returned set, timing, errors, optional downstream agent run id.

## MCP Tools (exactly six)

| Tool | Purpose |
|------|---------|
| `memory_propose` | Submit candidate memory. Must accept or infer scope — else stays `candidate`. |
| `memory_search` | Returns only `active` + in-validity-period records by default. Every result carries source summary, scope, state, hit reason. |
| `memory_get` | Detail + source + history. |
| `memory_correct` | Submit corrected version, preserves supersedes relationship. |
| `memory_forget` | Revoke or hard-purge. |
| `memory_explain` | Why was this returned? Who has read it? |

Agents never directly issue `approved` / `purged` — those are user-only high-privilege ops.

## Hard Rules (load-bearing)

1. **Never mutate event identity or history.** Corrections append new events; projections fold. Hard purge is the sole exception for destructive payload-field redaction, while event id/type/actor/time/links remain immutable.
2. **Scope before rank.** Filtering happens before FTS5 or embedding scoring.
3. **Projection rebuildable.** Dropping `MemoryRecord` and replaying events must reproduce all non-purged records.
4. **Purge ≠ delete row.** Must remove content column + FTS index + vector index in one txn, write contentless tombstone.
5. **Bind 127.0.0.1 by default.** Remote bind requires explicit auth key + visible warning.
6. **Logs/traces default-redact.** No full memory content, no secrets.
7. **Structured conflict only.** Only `subject+predicate+scope` matches auto-surface in Conflicts page. Free-text → suggestion only, human adjudicates.
8. **Trace semantics.** Use wording "read / injected / related run" — never claim strict causal proof of agent behavior.

## Commands (planned)

Once scaffolded:

```bash
# Backend
uv sync                              # install deps
uv run memory-workbench              # dev launch (serves API + UI)
uv run pytest                        # backend tests
uv run pytest tests/test_foo.py -k name  # single test
uv run ruff check .                  # lint
uv run mypy src/memory_workbench     # type check
uv run alembic upgrade head          # migrate

# Frontend (dev only — prod bundled by FastAPI)
cd frontend && pnpm install
pnpm dev                             # Vite dev server
pnpm test                            # Vitest
pnpm exec playwright test            # E2E
pnpm exec openapi-typescript http://127.0.0.1:8000/openapi.json -o src/generated/api.ts
```

## Milestones

- **A** — Runnable event ledger. SQLite schema, migrations, event append, projection rebuild test.
- **B** — Two-client MCP sharing. Six tools, FTS5 search, scope filter, JSONL import/export, Codex + second client docs.
- **C** — Web UI: Inbox, Explorer, Conflicts, Settings.
- **D** — Developer Trace page with bidirectional jumps.
- **E** — Install + first-run closed loop. Single Python process serving bundled UI, no Node for end users.

**Tracer-bullet (do this first, end-to-end thin slice)**:
> Start service → Client A proposes project memory → SQLite logs event → visible in Web UI → Client B searches → Trace visible → user corrects → Client B reads new value.

## Acceptance Highlights

- Two distinct MCP client ids connect to same local service.
- Project-scoped memory written by Client A is retrievable by Client B in same project; **invisible** to different project id by default.
- Correct op creates new event + new version, never in-place overwrite.
- `superseded / revoked / expired` records excluded from default search.
- JSONL round-trip restores all state + relations except purged content.
- FTS p95 < 200ms at 10k short memories (excluding external model calls).
- State machine + scope rule unit-test branch coverage ≥ 90%.
- First-run requires no API key; user connects two clients within 10 minutes.
- Core UI ops work at both 375px and 1280px widths.

## Explicit Non-Goals (MVP)

Cloud accounts, cross-device sync, team/RBAC/SSO, audit reports, knowledge graph dependency, self-built embedding/reranker, memory benchmarks, silent auto-capture of all conversations, reliable free-text auto-conflict, strict counterfactual replay (deferred to phase 2).

## Source of Truth Documents

- `docs/spec.md` (when written) — full PRD v0.1, 2026-07-16. Sections referenced above: §6 domain model, §7 MCP tools, §9 architecture, §11 milestones, §12 acceptance, §16 ADR.

When spec and code disagree, spec wins until spec is amended.
