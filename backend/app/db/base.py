"""Database bootstrap: SQLAlchemy engine + session + Base.

SQLite for local development/MVP; switching to PostgreSQL is an env-var change
(`SECUREUPI_DATABASE_URL`), nothing else.
"""
from __future__ import annotations

from typing import Callable, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core import config


class Base(DeclarativeBase):
    pass


def build_engine(url: str):
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        # check_same_thread=False: FastAPI calls get_db from worker threads.
        engine = create_engine(url, connect_args={"check_same_thread": False}, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _record):  # enforce FKs on SQLite too
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, **kwargs)


engine = build_engine(config.settings.database_url)
SessionLocal: Callable[..., Session] = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, future=True
)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. (MVP: create-if-missing; Alembic comes with PG deploy.)"""
    from app import models  # noqa: F401  (register mappings)

    Base.metadata.create_all(bind=engine)
