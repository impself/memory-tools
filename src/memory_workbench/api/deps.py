"""Process-wide engine + session factory.

Tracer-bullet uses module-level singleton. Production: dependency injection.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from memory_workbench.storage.db import (
    init_schema,
    make_engine,
    make_session_factory,
)

_engine: Engine | None = None
SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
        init_schema(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global SessionFactory
    if SessionFactory is None:
        SessionFactory = make_session_factory(get_engine())
    return SessionFactory


def session_dep() -> Session:
    """Open a new session. Caller closes."""
    return get_session_factory()()


def reset_for_tests(db_path: str = ":memory:") -> None:
    """Reset state — tests only."""
    global _engine, SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(db_path)
    init_schema(_engine)
    SessionFactory = make_session_factory(_engine)
