from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from checkers.base import CheckFinding


@dataclass
class QCResult:
    filename: str
    rel_path: str
    file_path: Path
    airtable_record_id: Optional[str]
    run_id: Optional[str]
    status: str                        # "pass" | "fail" | "error" | "skipped"
    findings: list[CheckFinding]
    duration: str                      # file duration in seconds as string
    actual_res: str                    # e.g. "2318x1632"
    meta: dict
    dest_path: Optional[Path]          # where the file was copied to if it passed
    pipeline_version: str
    checked_at: datetime


@dataclass
class JobSummary:
    project: str
    started_at: datetime
    completed_at: Optional[datetime]
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
