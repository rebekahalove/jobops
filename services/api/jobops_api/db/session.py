from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from jobops_api.settings import load_settings


def database_url_for_sqlalchemy(raw_url: str) -> str:
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql+psycopg://", 1)
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw_url


def create_db_engine(database_url: str | None = None) -> Engine:
    raw_url = database_url or load_settings().database_url
    if not raw_url:
        raise RuntimeError("DATABASE_URL is required for database access.")

    return create_engine(
        database_url_for_sqlalchemy(raw_url),
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or create_db_engine(), autoflush=False, autocommit=False)


def get_db_session() -> Iterator[Session]:
    session_factory = create_session_factory()
    with session_factory() as session:
        yield session
