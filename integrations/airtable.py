from __future__ import annotations

import logging
import os
from typing import Optional

from pyairtable import Api

from core.config import AirtableConfig
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

    def __init__(self, config: AirtableConfig) -> None:
        self._config = config
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
        formula = f"{{{qc_status_field}}} = \"{self._config.pending_value}\""

        try:
            raw_records = table.all(formula=formula)
        except Exception:
            logger.exception("Airtable get_pending_records failed")
            return []

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
        if not success:
            logger.warning("Aggregate write failed for record %s (%d file(s)).", record_id, len(results))

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

        try:
            table.update(record_id, fields)
            return True
        except Exception:
            logger.exception("Airtable _patch failed for record %s", record_id)
            return False
