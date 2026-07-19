.DEFAULT_GOAL := help

.PHONY: help install frontend-install test lint typecheck frontend-build check run mcp mcp-check release-checklist

help: ## Show available development commands
	@echo "Memory Workbench development commands"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install: ## Install Python development dependencies
	uv sync --extra dev

frontend-install: ## Install React and TypeScript dependencies
	cd frontend && npm install

test: ## Run the Python test suite
	uv run pytest -q

lint: ## Run Ruff static analysis
	uv run ruff check .

typecheck: ## Run strict Python type checking
	uv run mypy src/memory_workbench

frontend-build: ## Type-check and build the FastAPI-served frontend bundle
	cd frontend && npm run build

check: test lint typecheck frontend-build ## Run all automated checks

run: ## Start the local FastAPI application
	uv run memory-workbench

mcp: ## Start the packaged stdio MCP server (no HTTP)
	uv run memory-workbench-mcp

mcp-check: ## Verify the MCP console script is registered and starts a stdio server
	@uv run python -c "from importlib.metadata import entry_points; \
	names = [e.name for e in entry_points(group='console_scripts') if 'memory-workbench' in e.name]; \
	print('console scripts:', ', '.join(names)); \
	assert 'memory-workbench-mcp' in names, 'memory-workbench-mcp not registered'; \
	print('OK')"
	uv run pytest tests/test_mcp_entrypoint.py -q

release-checklist: ## Print the manual two-client release checklist (docs/mcp-client-guide.md)
	@echo "Manual release checklist (see docs/mcp-client-guide.md for full steps):"
	@echo "  1. make install && make frontend-build"
	@echo "  2. make check     # pytest + ruff + mypy + frontend build"
	@echo "  3. make mcp-check # console script registered and stdio smoke-tested"
	@echo "  4. uv tool install memory-workbench --force in a temp env"
	@echo "  5. Run memory-workbench-mcp with MW_CLIENT_ID=codex-local"
	@echo "  6. Run memory-workbench (Web UI) and bind a second client endpoint"
	@echo "  7. Two-client flow: propose -> approve -> search -> revoke"
	@echo "  8. Confirm Traces attribute each search to the right AgentAsset"
