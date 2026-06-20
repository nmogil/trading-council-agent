"""Database engine and session helpers.

Importing this module registers all tables (via ``trading_council.models``) on
``SQLModel.metadata`` so ``create_all`` builds the full schema.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine

from trading_council import models  # noqa: F401  registers tables on SQLModel.metadata

_SQLITE_PREFIX = "sqlite:///"


def _ensure_sqlite_parent(database_url: str) -> None:
    """Create the parent directory for a file-backed SQLite URL (no-op otherwise)."""
    if not database_url.startswith(_SQLITE_PREFIX):
        return
    path = database_url[len(_SQLITE_PREFIX) :]
    if not path or path.startswith(":memory:"):
        return
    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(database_url: str) -> Engine:
    """Build an engine, ensuring the SQLite parent dir exists first."""
    _ensure_sqlite_parent(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_db(database_url: str) -> Engine:
    """Create the engine and all tables. Returns the engine for reuse in tests."""
    engine = create_db_engine(database_url)
    SQLModel.metadata.create_all(engine)
    return engine


@contextmanager
def get_session(engine: Engine) -> Iterator[Session]:
    """Yield a session bound to ``engine``; caller owns commit/rollback."""
    with Session(engine) as session:
        yield session
