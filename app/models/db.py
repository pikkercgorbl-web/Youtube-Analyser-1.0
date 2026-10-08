import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def sqlalchemy_echo_enabled() -> bool:
    """SQLAlchemy statement echo (workers should set RADAR_SQL_ECHO=false)."""
    raw = os.environ.get("RADAR_SQL_ECHO")
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return settings.debug


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def _build_engine():
    url = settings.database_url
    kwargs: dict = {"echo": sqlalchemy_echo_enabled()}

    if url.startswith("sqlite"):
        if url.startswith("sqlite:///./"):
            db_path = url.removeprefix("sqlite:///./")
            Path("data").mkdir(parents=True, exist_ok=True)
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread is SQLite-only; omit for PostgreSQL.
        kwargs["connect_args"] = {"check_same_thread": False}
    elif url.startswith("postgresql"):
        kwargs["pool_pre_ping"] = True

    return create_engine(url, **kwargs)


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
