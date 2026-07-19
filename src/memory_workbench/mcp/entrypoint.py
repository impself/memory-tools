"""Entrypoint for the `memory-workbench-mcp` console script.

Starts the stdio MCP server only. Never starts FastAPI or Uvicorn. Plan
cross-tool-onboarding §2: a packaged command lets installed MCP clients
configure memory-workbench without invoking Python source through -c.
"""

from __future__ import annotations

from memory_workbench.mcp.server import run_stdio


def run() -> None:
    """Console-script entry point."""
    run_stdio()


if __name__ == "__main__":
    run()
