from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    String,
    create_engine,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

_PROJECT_ROOT = Path(__file__).parent.parent
_DEFAULT_DB_URL = f"sqlite:///{_PROJECT_ROOT / 'qc.db'}"


def _resolve_db_url(db_url: str | None) -> str:
    return db_url or os.environ.get("QC_DATABASE_URL") or _DEFAULT_DB_URL


class Base(DeclarativeBase):
    pass


class Result(Base):
    __tablename__ = "results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    airtable_record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    rel_path: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    airtable_synced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    checks: Mapped[list[Check]] = relationship("Check", back_populates="result", cascade="all, delete-orphan")


class Check(Base):
    __tablename__ = "checks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    result_id: Mapped[str] = mapped_column(String, ForeignKey("results.id"), nullable=False, index=True)
    checker: Mapped[str] = mapped_column(String, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    result: Mapped[Result] = relationship("Result", back_populates="checks")


def init_db(db_url: str | None = None) -> None:
    """Create all tables if they do not already exist."""
    engine = create_engine(_resolve_db_url(db_url), echo=False)
    Base.metadata.create_all(engine)
    engine.dispose()


@contextmanager
def get_session(db_url: str | None = None) -> Generator[Session, None, None]:
    """Context manager that yields a SQLAlchemy Session and commits on clean exit."""
    url = _resolve_db_url(db_url)
    engine = create_engine(url, echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            engine.dispose()


def save_result(session: Session, result_data: dict) -> Result:
    """Upsert a Result row by rel_path.

    result_data keys:
        filename, rel_path, status, pipeline_version (opt), checked_at (opt),
        meta (opt), airtable_record_id (opt), airtable_synced (opt)
    """
    rel_path = result_data["rel_path"]
    existing = get_result_by_rel_path(session, rel_path)

    if existing is None:
        result = Result(
            id=str(uuid.uuid4()),
            filename=result_data["filename"],
            rel_path=rel_path,
            status=result_data["status"],
            pipeline_version=result_data.get("pipeline_version"),
            checked_at=result_data.get("checked_at", datetime.now(timezone.utc)),
            meta=result_data.get("meta", {}),
            airtable_record_id=result_data.get("airtable_record_id"),
            airtable_synced=result_data.get("airtable_synced", False),
        )
        session.add(result)
    else:
        existing.filename = result_data["filename"]
        existing.status = result_data["status"]
        if "pipeline_version" in result_data:
            existing.pipeline_version = result_data["pipeline_version"]
        existing.checked_at = result_data.get("checked_at", datetime.now(timezone.utc))
        if "meta" in result_data:
            existing.meta = result_data["meta"]
        if "airtable_record_id" in result_data:
            existing.airtable_record_id = result_data["airtable_record_id"]
        if "airtable_synced" in result_data:
            existing.airtable_synced = result_data["airtable_synced"]
        result = existing

    return result


def get_result_by_rel_path(session: Session, rel_path: str) -> Result | None:
    return session.execute(
        select(Result).where(Result.rel_path == rel_path)
    ).scalar_one_or_none()


def has_passed(session: Session, rel_path: str) -> bool:
    """Return True if the file has a passing or overridden result on record."""
    result = get_result_by_rel_path(session, rel_path)
    if result is None:
        return False
    return result.status in ("pass", "overridden")


def get_unsynced_results(session: Session) -> list[Result]:
    """Return all results that have not been synced to Airtable yet."""
    return list(
        session.execute(
            select(Result).where(Result.airtable_synced.is_(False))
        ).scalars().all()
    )
