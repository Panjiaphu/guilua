from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings


GROUP_V3_SCHEMA_REVISION = "20260907_0024"


class Base(DeclarativeBase):
    pass


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def normalize_database_url(database_url: str) -> str:
    """Select the installed psycopg v3 driver for Render-style PostgreSQL URLs."""

    normalized = database_url.strip()
    if normalized.startswith("postgresql://"):
        return "postgresql+psycopg://" + normalized.removeprefix("postgresql://")
    if normalized.startswith("postgres://"):
        return "postgresql+psycopg://" + normalized.removeprefix("postgres://")
    return normalized


class Database:
    def __init__(self, settings: Settings):
        database_url = normalize_database_url(settings.database_url)
        if database_url.startswith("sqlite:///./"):
            relative = database_url.removeprefix("sqlite:///./")
            Path(relative).parent.mkdir(parents=True, exist_ok=True)
        engine_options: dict = {
            "pool_pre_ping": True,
            "future": True,
        }
        if database_url.startswith("sqlite"):
            engine_options["connect_args"] = {"check_same_thread": False}
        else:
            engine_options.update(
                {
                    "pool_size": settings.database_pool_size,
                    "max_overflow": settings.database_max_overflow,
                    "pool_recycle": 1800,
                }
            )
        self.engine: Engine = create_engine(database_url, **engine_options)
        if database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )

    def session(self) -> Session:
        return self.session_factory()

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def migration_revisions(self) -> tuple[str, ...]:
        """Return the applied Alembic heads without exposing database details."""

        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT version_num FROM alembic_version"))
            return tuple(sorted(str(row[0]) for row in rows if row[0]))

    def group_v3_schema_ready(self) -> bool:
        return self.migration_revisions() == (GROUP_V3_SCHEMA_REVISION,)

    def dispose(self) -> None:
        self.engine.dispose()
