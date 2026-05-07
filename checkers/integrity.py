from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path
from typing import Optional

from checkers.base import BaseChecker, CheckFinding
from core.registry import register

_PTS_SIZE_LIMIT = 500 * 1024 * 1024  # 500 MB
_MAX_REPORTED_DISCONTINUITIES = 5


@register("integrity")
class IntegrityChecker(BaseChecker):
    def run(self, file_path: Path) -> list[CheckFinding]:
        findings: list[CheckFinding] = []

        try:
            size = file_path.stat().st_size
        except OSError as e:
            return [self._finding(
                passed=False,
                severity="error",
                message=f"Cannot stat file: {e}",
            )]

        if size == 0:
            return [self._finding(
                passed=False,
                severity="error",
                message="File is empty (0 bytes).",
                details={"file_size_bytes": 0},
            )]

        if size < 1024:
            findings.append(self._finding(
                passed=False,
                severity="warning",
                message=f"File is suspiciously small ({size} bytes).",
                details={"file_size_bytes": size},
            ))
        else:
            findings.append(self._finding(
                passed=True,
                severity="info",
                message=f"File size {size} bytes is within normal range.",
                details={"file_size_bytes": size},
            ))

        if file_path.suffix.lower() in (".jpg", ".png"):
            return findings

        if size > _PTS_SIZE_LIMIT:
            size_mb = size // (1024 * 1024)
            findings.append(self._finding(
                passed=True,
                severity="info",
                message=f"PTS check skipped for large file (>{size_mb}MB).",
                details={"file_size_bytes": size, "size_mb": size_mb},
            ))
            return findings

        findings.extend(self._check_pts(file_path))
        return findings

    def _check_pts(self, file_path: Path) -> list[CheckFinding]:
        command = [
            "ffprobe",
            "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "frame=pts_time",
            "-print_format", "json",
            str(file_path),
        ]

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            return [self._finding(
                passed=False,
                severity="error",
                message=f"ffprobe PTS check failed: {e}",
            )]
        except (json.JSONDecodeError, Exception) as e:
            return [self._finding(
                passed=False,
                severity="error",
                message=f"Failed to parse ffprobe PTS output: {e}",
            )]

        frames = data.get("frames", [])
        pts_values: list[float] = []
        for frame in frames:
            raw = frame.get("pts_time") or frame.get("pkt_pts_time")
            if raw is not None:
                try:
                    pts_values.append(float(raw))
                except (ValueError, TypeError):
                    pass

        if len(pts_values) < 2:
            return [self._finding(
                passed=True,
                severity="info",
                message="Too few frames to perform PTS discontinuity check.",
            )]

        deltas = [pts_values[i + 1] - pts_values[i] for i in range(len(pts_values) - 1)]
        positive_deltas = [d for d in deltas if d > 0]

        if not positive_deltas:
            return [self._finding(
                passed=True,
                severity="info",
                message="PTS discontinuity check: no valid frame deltas found.",
            )]

        expected_frame_dur = statistics.median(positive_deltas)
        threshold = expected_frame_dur * 2.0

        discontinuities = [
            (pts_values[i], deltas[i])
            for i, delta in enumerate(deltas)
            if delta > threshold
        ]

        if not discontinuities:
            return [self._finding(
                passed=True,
                severity="info",
                message="No PTS discontinuities detected.",
                details={"expected_frame_duration": expected_frame_dur},
            )]

        findings: list[CheckFinding] = []
        for gap_at, gap_duration in discontinuities[:_MAX_REPORTED_DISCONTINUITIES]:
            findings.append(self._finding(
                passed=False,
                severity="warning",
                message=(
                    f"PTS discontinuity at {gap_at:.3f}s: "
                    f"gap of {gap_duration:.3f}s (expected ~{expected_frame_dur:.4f}s per frame)."
                ),
                details={
                    "gap_at_seconds": gap_at,
                    "gap_duration_seconds": gap_duration,
                    "expected_frame_duration": expected_frame_dur,
                },
            ))

        total = len(discontinuities)
        if total > _MAX_REPORTED_DISCONTINUITIES:
            findings.append(self._finding(
                passed=False,
                severity="warning",
                message=f"{total - _MAX_REPORTED_DISCONTINUITIES} additional PTS discontinuities not listed.",
                details={"total_discontinuities": total},
            ))

        return findings
