.DEFAULT_GOAL := help

.PHONY: help install frontend-install test lint typecheck frontend-build check run

help: ## Show available development commands
	@echo "Memory Workbench development commands"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

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
