from __future__ import annotations

import logging
import os
from typing import Optional

from pyairtable import Api

from core.config import AirtableConfig
from core.database import get_session
from core.models import JobSummary, QCResult
from integrations.base import BaseIntegration

logger = logging.getLogger(__name__)

_STATUS_PRIORITY = {"fail": 2, "error": 1, "pass": 0}


class AirtableIntegration(BaseIntegration):
    """Reads pending QC records from Airtable and writes results back.

    Results are buffered per record_id and written once in on_job_complete.
    This means a single Airtable record that expands to multiple files (e.g. a
    directory path) gets one aggregate write rather than one write per file.
    """

    def __init__(self, config: AirtableConfig, db_url: Optional[str] = None) -> None:
        self._config = config
        self._db_url = db_url
        self._table: Optional[object] = None
        self._buffered: dict[str, list[QCResult]] = {}

    def _get_table(self) -> Optional[object]:
        if self._table is not None:
            return self._table
        api_key = os.environ.get("AIRTABLE_API_KEY")
        if not api_key:
            logger.warning("AIRTABLE_API_KEY is not set; Airtable integration disabled.")
            return None
        api = Api(api_key)
        self._table = api.table(self._config.base_id, self._config.table_id)
        return self._table

    def get_pending_records(self) -> list[dict]:
        """Return records where qc_status == config.pending_value.

        Each item: {"record_id": str, "file_path": str | None, "raw": dict}
        Returns [] on any API failure.
        """
        table = self._get_table()
        if table is None:
            return []

        qc_status_field = self._config.fields.get("qc_status", "QC Status")
        file_path_field = self._config.fields.get("file_path", "File Path")
        clauses = [f"{{{qc_status_field}}} = \"{v}\"" for v in self._config.pending_values]
        formula = f"OR({', '.join(clauses)})" if len(clauses) > 1 else clauses[0]

        logger.info("Airtable query — table: %s  formula: %s", self._config.table_id, formula)
        try:
            raw_records = table.all(formula=formula)
        except Exception:
            logger.exception("Airtable get_pending_records failed")
            return []

        logger.info("Airtable returned %d pending record(s).", len(raw_records))
        if not raw_records:
            logger.warning(
                "Zero pending records found. Verify that field '%s' exists in the table "
                "and that one of %s is a valid option value.",
                qc_status_field,
                self._config.pending_values,
            )

        return [
            {
                "record_id": record["id"],
                "file_path": record.get("fields", {}).get(file_path_field),
                "raw": record.get("fields", {}),
            }
            for record in raw_records
        ]

    def write_result(self, record_id: str, result: QCResult) -> bool:
        """Patch an Airtable record with the outcome of a single QCResult.

        Public API for one-off writes (e.g. retries). The normal pipeline path
        uses _on_record_complete / _on_job_complete for buffered aggregate writes.
        """
        error_messages = [
            f.message for f in result.findings if not f.passed and f.severity == "error"
        ]
        return self._patch(record_id, result.status, error_messages, result.checked_at.isoformat(), result.pipeline_version)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_record_complete(self, result: QCResult) -> None:
        if result.airtable_record_id is None:
            return
        self._buffered.setdefault(result.airtable_record_id, []).append(result)

    def _on_job_complete(self, summary: JobSummary, results: list[QCResult]) -> None:
        for record_id, file_results in self._buffered.items():
            self._write_aggregate(record_id, file_results)
        self._buffered.clear()

    def _write_aggregate(self, record_id: str, results: list[QCResult]) -> None:
        """Write the aggregate outcome for one or more files sharing a record_id."""
        worst_status = max((r.status for r in results), key=lambda s: _STATUS_PRIORITY.get(s, 0))
        multi = len(results) > 1

        all_errors: list[str] = []
        for r in results:
            errs = [f.message for f in r.findings if not f.passed and f.severity == "error"]
            if errs:
                prefix = f"[{r.filename}] " if multi else ""
                all_errors.extend(f"{prefix}{e}" for e in errs)

        representative = max(results, key=lambda r: _STATUS_PRIORITY.get(r.status, 0))
        success = self._patch(
            record_id,
            worst_status,
            all_errors,
            representative.checked_at.isoformat(),
            representative.pipeline_version,
        )
        if success:
            self._mark_synced(results)
        else:
            logger.warning("Aggregate write failed for record %s (%d file(s)).", record_id, len(results))

    def _mark_synced(self, results: list[QCResult]) -> None:
        """Flip airtable_synced=True in SQLite for all results in this batch."""
        if not self._db_url:
            return
        from sqlalchemy import select, update
        from core.database import Result
        ids = [r.rel_path for r in results]
        try:
            with get_session(self._db_url) as session:
                session.execute(
                    update(Result)
                    .where(Result.rel_path.in_(ids))
                    .values(airtable_synced=True)
                )
        except Exception:
            logger.exception("Failed to mark results as synced for %s", ids)

    def write_override(self, record_id: str, failure_messages: list[str], version: str) -> bool:
        """Mark a record as Approved in Airtable after a manual override.

        Writes the pass status and a note in the qc_errors field documenting
        that the override was done by JA and listing the original failures.
        """
        from datetime import datetime, timezone
        lines = ["Overridden by JA"]
        if failure_messages:
            lines.append("")
            lines.append("Original failures:")
            for msg in failure_messages:
                lines.append(f"• {msg}")
        return self._patch(
            record_id,
            status="pass",
            error_messages=lines,
            checked_at=datetime.now(timezone.utc).isoformat(),
            version=version,
        )

    def _patch(self, record_id: str, status: str, error_messages: list[str], checked_at: str, version: str) -> bool:
        """Build and send the Airtable field update. Only sends configured fields."""
        table = self._get_table()
        if table is None:
            return False

        _f = self._config.fields
        fields: dict = {}
        if "qc_status" in _f:
            fields[_f["qc_status"]] = self._config.status_values.get(status, status)
        if "qc_errors" in _f:
            fields[_f["qc_errors"]] = "\n".join(error_messages)
        if "qc_checked_at" in _f:
            fields[_f["qc_checked_at"]] = checked_at
        if "qc_version" in _f:
            fields[_f["qc_version"]] = version

        logger.info("Airtable patch — record: %s  fields: %s", record_id, list(fields.keys()))
        try:
            table.update(record_id, fields)
            return True
        except Exception:
            logger.exception(
                "Airtable _patch failed for record %s. Fields attempted: %s. "
                "Check that these field names exist in the table and that status value '%s' "
                "is a valid Select option.",
                record_id,
                list(fields.keys()),
                fields.get(self._config.fields.get("qc_status", ""), "?"),
            )
            return False
