"""Engine + sessionmaker factory.

Default DB path is `./memory_workbench.db` in CWD. Override via env
`MW_DB_PATH` (use `:memory:` for tests).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from memory_workbench.storage.tables import Base


def _default_db_path() -> str:
    env = os.environ.get("MW_DB_PATH")
    if env:
        return env
    return str(Path.cwd() / "memory_workbench.db")


def make_engine(db_path: str | None = None):
    path = db_path or _default_db_path()
    url = f"sqlite:///{path}"
    if path == ":memory:":
        # In-memory needs StaticPool so all sessions share one connection,
        # otherwise each session sees a fresh empty database.
        return create_engine(
            url,
            future=True,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    return create_engine(url, future=True, connect_args={"check_same_thread": False})


def init_schema(engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
