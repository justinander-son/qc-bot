# tests/test_integrations.py
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch


def _make_summary():
    from core.models import JobSummary
    return JobSummary(
        project="test",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        total=5,
        passed=4,
        failed=1,
        skipped=0,
        errors=0,
    )


def test_base_integration_swallows_exception():
    from integrations.base import BaseIntegration

    class Broken(BaseIntegration):
        def _on_job_start(self, summary):
            raise RuntimeError("boom")

    b = Broken()
    b.on_job_start(_make_summary())  # must not raise


def test_airtable_no_api_key_returns_empty(monkeypatch):
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    from core.config import AirtableConfig
    from integrations.airtable import AirtableIntegration
    cfg = AirtableConfig(
        base_id="appTEST",
        table_id="tblTEST",
        fields={
            "qc_status": "QC Status",
            "file_path": "File Path",
            "qc_errors": "QC Errors",
            "qc_checked_at": "QC Checked At",
            "qc_version": "QC Version",
        },
        pending_values=["Pending"],
    )
    ai = AirtableIntegration(cfg)
    assert ai.get_pending_records() == []


def test_airtable_write_result_no_api_key_returns_false(monkeypatch):
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    from core.config import AirtableConfig
    from integrations.airtable import AirtableIntegration
    from core.models import QCResult
    from pathlib import Path
    cfg = AirtableConfig(
        base_id="appTEST",
        table_id="tblTEST",
        fields={
            "qc_status": "QC Status",
            "file_path": "File Path",
            "qc_errors": "QC Errors",
            "qc_checked_at": "QC Checked At",
            "qc_version": "QC Version",
        },
        pending_values=["Pending"],
    )
    ai = AirtableIntegration(cfg)
    result = QCResult(
        filename="test.mp4",
        rel_path="test.mp4",
        file_path=Path("test.mp4"),
        airtable_record_id="recTEST",
        run_id=None,
        status="pass",
        findings=[],
        duration="2.0",
        actual_res="2318x1632",
        meta={},
        dest_path=None,
        pipeline_version="2.0.0",
        checked_at=datetime.now(timezone.utc),
    )
    assert ai.write_result("recTEST", result) is False


def test_slack_no_webhook_noop():
    from integrations.notifications import SlackNotification
    sn = SlackNotification("")
    sn.on_job_complete(_make_summary(), [])  # must not raise


def test_slack_bad_url_noop():
    from integrations.notifications import SlackNotification
    sn = SlackNotification("http://localhost:19999/definitely_down")
    sn.on_job_complete(_make_summary(), [])  # must not raise
