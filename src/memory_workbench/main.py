"""FastAPI app entry. Serves HTTP API + static UI on 127.0.0.1."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from memory_workbench.api.deps import get_engine
from memory_workbench.api.routes import router

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    # Init DB on first import via deps.get_engine()
    get_engine()

    app = FastAPI(
        title="Memory Workbench",
        version="0.1.0",
        description="Local-first Agent Memory Control Plane — tracer-bullet",
    )
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def run() -> None:
    """Entry point for `memory-workbench` script."""
    uvicorn.run(
        "memory_workbench.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
