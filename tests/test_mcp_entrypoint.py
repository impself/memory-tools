"""Installed MCP command smoke test."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


def test_packaged_mcp_stdio_entrypoint_starts(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["MW_CLIENT_ID"] = "stdio-contract-client"
    environment["MW_DB_PATH"] = str(tmp_path / "memory-workbench.db")

    process = subprocess.Popen(
        ["uv", "run", "memory-workbench-mcp"],
        cwd=project_root,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # A packaged command must remain a stdio server rather than exit or
        # start the FastAPI HTTP server.
        time.sleep(0.75)
        assert process.poll() is None
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
