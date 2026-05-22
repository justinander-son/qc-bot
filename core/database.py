from __future__ import annotations

import logging
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
    Integer,
    JSON,
    String,
    and_,
    create_engine,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_DEFAULT_DB_URL = f"sqlite:///{_PROJECT_ROOT / 'qc.db'}"


def _resolve_db_url(db_url: str | None) -> str:
    return db_url or os.environ.get("QC_DATABASE_URL") or _DEFAULT_DB_URL


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One pipeline execution — analogous to a commit snapshot."""
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    results: Mapped[list[Result]] = relationship("Result", back_populates="run", cascade="all, delete-orphan")


class Result(Base):
    __tablename__ = "results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("runs.id"), nullable=True, index=True)
    airtable_record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    # Not unique — the same file can appear in multiple runs.
    rel_path: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    pipeline_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    airtable_synced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    run: Mapped[Optional[Run]] = relationship("Run", back_populates="results")
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


# ── Schema migration ───────────────────────────────────────────────────────────

def _needs_migration(engine) -> bool:
    """True if the DB is pre-runs schema (missing runs table or run_id column)."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "runs" not in tables:
        return True
    if "results" in tables:
        cols = {c["name"] for c in inspector.get_columns("results")}
        if "run_id" not in cols:
            return True
    return False


def _migrate(engine) -> None:
    """Drop all tables and recreate. Safe because Airtable is the authoritative store."""
    logger.warning("QC database schema migration: dropping and recreating all tables.")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


# ── Public API ─────────────────────────────────────────────────────────────────

def init_db(db_url: str | None = None) -> None:
    """Create tables (or migrate schema) as needed."""
    engine = create_engine(_resolve_db_url(db_url), echo=False)
    if _needs_migration(engine):
        _migrate(engine)
    else:
        Base.metadata.create_all(engine)
    engine.dispose()


@contextmanager
def get_session(db_url: str | None = None) -> Generator[Session, None, None]:
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


# ── Run management ─────────────────────────────────────────────────────────────

def create_run(session: Session, project: str, started_at: datetime) -> Run:
    run = Run(id=str(uuid.uuid4()), project=project, started_at=started_at)
    session.add(run)
    session.flush()
    return run


def finalise_run(session: Session, run_id: str, summary: dict) -> None:
    run = session.execute(select(Run).where(Run.id == run_id)).scalar_one_or_none()
    if run is None:
        return
    run.completed_at = summary.get("completed_at")
    run.total = summary.get("total", 0)
    run.passed = summary.get("passed", 0)
    run.failed = summary.get("failed", 0)
    run.skipped = summary.get("skipped", 0)
    run.errors = summary.get("errors", 0)


def get_runs(session: Session) -> list[Run]:
    return list(
        session.execute(select(Run).order_by(Run.started_at.desc())).scalars().all()
    )


def delete_run(session: Session, run_id: str) -> None:
    """Delete a run and all its results/checks (via cascade)."""
    run = session.execute(select(Run).where(Run.id == run_id)).scalar_one_or_none()
    if run:
        session.delete(run)


def get_results_for_run(session: Session, run_id: str) -> list[Result]:
    return list(
        session.execute(
            select(Result)
            .where(Result.run_id == run_id)
            .order_by(Result.checked_at.desc())
        ).scalars().all()
    )


def get_latest_results_for_run(session: Session, run_id: str) -> list[tuple[Result, int]]:
    """Return (latest_result, attempt_count) per rel_path for a run.

    For files processed only once, attempt_count is 1. On retries the same
    rel_path gets a new Result row; this query surfaces only the most recent
    row for each file, with a count of how many attempts exist.
    """
    latest_subq = (
        select(Result.rel_path, func.max(Result.checked_at).label("max_at"))
        .where(Result.run_id == run_id)
        .group_by(Result.rel_path)
        .subquery()
    )
    count_subq = (
        select(Result.rel_path, func.count(Result.id).label("attempt_count"))
        .where(Result.run_id == run_id)
        .group_by(Result.rel_path)
        .subquery()
    )
    rows = session.execute(
        select(Result, count_subq.c.attempt_count)
        .join(latest_subq, and_(
            Result.rel_path == latest_subq.c.rel_path,
            Result.checked_at == latest_subq.c.max_at,
        ))
        .join(count_subq, Result.rel_path == count_subq.c.rel_path)
        .where(Result.run_id == run_id)
        .order_by(Result.checked_at.desc())
    ).all()
    return [(row[0], row[1]) for row in rows]


def recompute_run_stats(session: Session, run_id: str) -> None:
    """Recalculate a Run's aggregate counters from its latest-per-file results.

    Used after a retry so the Run row reflects the cumulative final state
    rather than just the most recent batch of files processed.
    """
    run = session.execute(select(Run).where(Run.id == run_id)).scalar_one_or_none()
    if run is None:
        return
    latest = get_latest_results_for_run(session, run_id)
    statuses = [r.status for r, _ in latest]
    run.total = len(statuses)
    run.passed = sum(1 for s in statuses if s in ("pass", "overridden"))
    run.failed = sum(1 for s in statuses if s == "fail")
    run.skipped = sum(1 for s in statuses if s == "skipped")
    run.errors = sum(1 for s in statuses if s == "error")
    run.completed_at = datetime.now(timezone.utc)


# ── Result management ──────────────────────────────────────────────────────────

def save_result(session: Session, result_data: dict) -> Result:
    """Insert a new Result row. One record per file per run — no upsert."""
    result = Result(
        id=str(uuid.uuid4()),
        run_id=result_data.get("run_id"),
        filename=result_data["filename"],
        rel_path=result_data["rel_path"],
        status=result_data["status"],
        pipeline_version=result_data.get("pipeline_version"),
        checked_at=result_data.get("checked_at", datetime.now(timezone.utc)),
        meta=result_data.get("meta", {}),
        airtable_record_id=result_data.get("airtable_record_id"),
        airtable_synced=result_data.get("airtable_synced", False),
    )
    session.add(result)
    return result


def has_passed(session: Session, rel_path: str) -> bool:
    """True if the file has a passing or overridden result in any run."""
    result = session.execute(
        select(Result)
        .where(Result.rel_path == rel_path)
        .where(Result.status.in_(["pass", "overridden"]))
        .limit(1)
    ).scalar_one_or_none()
    return result is not None


def get_unsynced_results(session: Session) -> list[Result]:
    return list(
        session.execute(
            select(Result).where(Result.airtable_synced.is_(False))
        ).scalars().all()
    )
