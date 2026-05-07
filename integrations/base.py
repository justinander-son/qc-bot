from __future__ import annotations

import logging
from abc import ABC

from core.models import JobSummary, QCResult

logger = logging.getLogger(__name__)


class BaseIntegration(ABC):
    """Abstract base for pipeline integrations.

    All hooks have no-op defaults so subclasses only override what they need.
    Every hook is wrapped in try/except so a failing integration never propagates
    to the pipeline.
    """

    def on_job_start(self, summary: JobSummary) -> None:
        try:
            self._on_job_start(summary)
        except Exception:
            logger.exception("%s.on_job_start failed", type(self).__name__)

    def on_record_complete(self, result: QCResult) -> None:
        try:
            self._on_record_complete(result)
        except Exception:
            logger.exception("%s.on_record_complete failed", type(self).__name__)

    def on_job_complete(self, summary: JobSummary, results: list[QCResult]) -> None:
        try:
            self._on_job_complete(summary, results)
        except Exception:
            logger.exception("%s.on_job_complete failed", type(self).__name__)

    # Subclasses override the _private variants; the public methods above add
    # the safety wrapper so subclass code never needs its own try/except.
    def _on_job_start(self, summary: JobSummary) -> None:
        pass

    def _on_record_complete(self, result: QCResult) -> None:
        pass

    def _on_job_complete(self, summary: JobSummary, results: list[QCResult]) -> None:
        pass
