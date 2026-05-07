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
    assert "results" in tables
    assert "checks" in tables
    engine.dispose()


def test_save_result_new(db_url):
    from core.database import init_db, get_session, save_result, get_result_by_rel_path
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
        fetched = get_result_by_rel_path(session, "folder/test.mp4")
        assert fetched is not None
        assert fetched.status == "pass"
        assert fetched.meta["shot"] == "001"


def test_save_result_upsert(db_url):
    from core.database import init_db, get_session, save_result, get_result_by_rel_path
    init_db(db_url)
    rel = "upsert/test.mp4"
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
        r = get_result_by_rel_path(session, rel)
        assert r.status == "pass"


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
