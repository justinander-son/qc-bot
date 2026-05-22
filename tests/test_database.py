# tests/test_database.py
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import inspect, text


def test_init_db_creates_tables(db_url):
    from core.database import init_db, Base
    from sqlalchemy import create_engine
    init_db(db_url)
    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "runs" in tables
    assert "results" in tables
    assert "checks" in tables
    engine.dispose()


def test_save_result_new(db_url):
    from core.database import init_db, get_session, save_result, Result
    from sqlalchemy import select
    init_db(db_url)
    data = {
        "filename": "test.mp4",
        "rel_path": "folder/test.mp4",
        "status": "pass",
        "pipeline_version": "2.0.0",
        "checked_at": datetime.now(timezone.utc),
        "meta": {"shot": "001"},
    }
    with get_session(db_url) as session:
        r = save_result(session, data)
        assert r.id is not None

    with get_session(db_url) as session:
        fetched = session.execute(
            select(Result).where(Result.rel_path == "folder/test.mp4")
        ).scalar_one_or_none()
        assert fetched is not None
        assert fetched.status == "pass"
        assert fetched.meta["shot"] == "001"


def test_save_result_insert_only(db_url):
    """Each call to save_result inserts a new row — no upsert."""
    from core.database import init_db, get_session, save_result, Result
    from sqlalchemy import select
    init_db(db_url)
    rel = "multi/test.mp4"
    with get_session(db_url) as session:
        save_result(session, {
            "filename": "test.mp4", "rel_path": rel, "status": "fail",
            "checked_at": datetime.now(timezone.utc), "meta": {},
        })
    with get_session(db_url) as session:
        save_result(session, {
            "filename": "test.mp4", "rel_path": rel, "status": "pass",
            "checked_at": datetime.now(timezone.utc), "meta": {},
        })
    with get_session(db_url) as session:
        rows = session.execute(
            select(Result).where(Result.rel_path == rel)
        ).scalars().all()
        assert len(rows) == 2
        statuses = {r.status for r in rows}
        assert statuses == {"fail", "pass"}


def test_has_passed_true(db_url):
    from core.database import init_db, get_session, save_result, has_passed
    init_db(db_url)
    with get_session(db_url) as session:
        save_result(session, {
            "filename": "a.mp4", "rel_path": "a.mp4", "status": "pass",
            "checked_at": datetime.now(timezone.utc), "meta": {},
        })
    with get_session(db_url) as session:
        assert has_passed(session, "a.mp4") is True


def test_has_passed_false(db_url):
    from core.database import init_db, get_session, save_result, has_passed
    init_db(db_url)
    with get_session(db_url) as session:
        save_result(session, {
            "filename": "b.mp4", "rel_path": "b.mp4", "status": "fail",
            "checked_at": datetime.now(timezone.utc), "meta": {},
        })
    with get_session(db_url) as session:
        assert has_passed(session, "b.mp4") is False


def test_has_passed_missing(db_url):
    from core.database import init_db, get_session, has_passed
    init_db(db_url)
    with get_session(db_url) as session:
        assert has_passed(session, "nonexistent.mp4") is False


def test_get_latest_results_for_run_single_attempt(db_url):
    """With one result per file, get_latest_results_for_run returns attempt_count=1."""
    from core.database import init_db, get_session, save_result, create_run, get_latest_results_for_run
    from datetime import datetime, timezone
    init_db(db_url)
    with get_session(db_url) as session:
        run = create_run(session, "test", datetime.now(timezone.utc))
        run_id = run.id
        save_result(session, {
            "filename": "a.mp4", "rel_path": "a.mp4", "status": "fail",
            "run_id": run_id, "checked_at": datetime.now(timezone.utc), "meta": {},
        })
    with get_session(db_url) as session:
        pairs = get_latest_results_for_run(session, run_id)
        assert len(pairs) == 1
        result, count = pairs[0]
        assert result.status == "fail"
        assert count == 1


def test_get_latest_results_for_run_multiple_attempts(db_url):
    """After a retry, get_latest_results_for_run returns the latest result with attempt_count=2."""
    from core.database import init_db, get_session, save_result, create_run, get_latest_results_for_run
    from datetime import datetime, timezone, timedelta
    init_db(db_url)
    t0 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    with get_session(db_url) as session:
        run = create_run(session, "test", t0)
        run_id = run.id
        save_result(session, {
            "filename": "b.mp4", "rel_path": "b.mp4", "status": "fail",
            "run_id": run_id, "checked_at": t0, "meta": {},
        })
        save_result(session, {
            "filename": "b.mp4", "rel_path": "b.mp4", "status": "pass",
            "run_id": run_id, "checked_at": t0 + timedelta(minutes=5), "meta": {},
        })
    with get_session(db_url) as session:
        pairs = get_latest_results_for_run(session, run_id)
        assert len(pairs) == 1
        result, count = pairs[0]
        assert result.status == "pass"
        assert count == 2


def test_recompute_run_stats(db_url):
    """recompute_run_stats reflects the latest result per file, not raw row counts."""
    from core.database import init_db, get_session, save_result, create_run, recompute_run_stats, get_runs
    from datetime import datetime, timezone, timedelta
    init_db(db_url)
    t0 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    with get_session(db_url) as session:
        run = create_run(session, "test", t0)
        run_id = run.id
        # file A: failed then passed (retry)
        save_result(session, {
            "filename": "a.mp4", "rel_path": "a.mp4", "status": "fail",
            "run_id": run_id, "checked_at": t0, "meta": {},
        })
        save_result(session, {
            "filename": "a.mp4", "rel_path": "a.mp4", "status": "pass",
            "run_id": run_id, "checked_at": t0 + timedelta(minutes=5), "meta": {},
        })
        # file B: failed only
        save_result(session, {
            "filename": "b.mp4", "rel_path": "b.mp4", "status": "fail",
            "run_id": run_id, "checked_at": t0, "meta": {},
        })
    with get_session(db_url) as session:
        recompute_run_stats(session, run_id)
    with get_session(db_url) as session:
        runs = get_runs(session)
        r = next(x for x in runs if x.id == run_id)
        assert r.total == 2
        assert r.passed == 1
        assert r.failed == 1


def test_get_unsynced_results(db_url):
    from core.database import init_db, get_session, save_result, get_unsynced_results
    init_db(db_url)
    with get_session(db_url) as session:
        save_result(session, {
            "filename": "c.mp4", "rel_path": "c.mp4", "status": "pass",
            "checked_at": datetime.now(timezone.utc), "meta": {},
            "airtable_synced": False,
        })
        save_result(session, {
            "filename": "d.mp4", "rel_path": "d.mp4", "status": "pass",
            "checked_at": datetime.now(timezone.utc), "meta": {},
            "airtable_synced": True,
        })
    with get_session(db_url) as session:
        unsynced = get_unsynced_results(session)
        rel_paths = [r.rel_path for r in unsynced]
        assert "c.mp4" in rel_paths
        assert "d.mp4" not in rel_paths
