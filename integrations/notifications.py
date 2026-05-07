from __future__ import annotations

import json
import logging
import os
import urllib.request
from core.models import JobSummary, QCResult
from integrations.base import BaseIntegration

logger = logging.getLogger(__name__)


class SlackNotification(BaseIntegration):
    """Posts a plain-text job summary to a Slack incoming webhook.

    Completely fail-safe: any exception is caught and logged, never raised.
    If SLACK_WEBHOOK_URL is not set the hook is a silent no-op.
    """

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def _on_job_complete(self, summary: JobSummary, results: list[QCResult]) -> None:
        if not self._webhook_url:
            return

        elapsed = "unknown"
        if summary.completed_at and summary.started_at:
            delta = summary.completed_at - summary.started_at
            total_seconds = int(delta.total_seconds())
            minutes, seconds = divmod(total_seconds, 60)
            elapsed = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

        text = (
            f"QC Run Complete — {summary.project}\n"
            f"Files: {summary.total} | Passed: {summary.passed} | "
            f"Failed: {summary.failed} | Skipped: {summary.skipped}\n"
            f"Duration: {elapsed}"
        )

        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            self._webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    logger.warning(
                        "Slack webhook returned non-200 status: %s", response.status
                    )
        except Exception:
            logger.exception("Slack notification failed")
