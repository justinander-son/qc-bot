from __future__ import annotations

import re
import subprocess
from pathlib import Path

from checkers.base import BaseChecker, CheckFinding
from core.registry import register


@register("content")
class ContentChecker(BaseChecker):
    def run(self, file_path: Path) -> list[CheckFinding]:
        return self._run_with_duration(file_path, total_duration=None)

    def run_with_duration(self, file_path: Path, total_duration: float) -> list[CheckFinding]:
        return self._run_with_duration(file_path, total_duration)

    def _run_with_duration(self, file_path: Path, total_duration) -> list[CheckFinding]:
        findings: list[CheckFinding] = []

        if file_path.suffix.lower() in (".jpg", ".png"):
            findings.append(self._finding(passed=True, severity="info", message="Image file; content checks skipped."))
            return findings

        if total_duration is None:
            total_duration = 999999.0

        qc = self._config.qc
        black_filter = (
            f"blackdetect=d={qc.black_sensitivity_duration}"
            f":pix_th={qc.black_pixel_threshold}"
            f":pic_th={qc.black_picture_threshold}"
        )
        freeze_filter = f"freezedetect=n={qc.freeze_noise_floor}:d={qc.freeze_sensitivity_duration}"

        try:
            result = subprocess.run(
                ["ffmpeg", "-v", "info", "-i", str(file_path),
                 "-vf", f"{black_filter},{freeze_filter}", "-f", "null", "-"],
                capture_output=True, text=True,
            )
            stderr_output = result.stderr
        except Exception as e:
            findings.append(self._finding(passed=False, severity="error", message=f"FFmpeg content check failed: {e}"))
            return findings

        black_re = re.compile(r"black_start:([\d\.]+) black_end:([\d\.]+) black_duration:([\d\.]+)")
        freeze_re = re.compile(r"freeze_start:([\d\.]+) freeze_end:([\d\.]+) freeze_duration:([\d\.]+)")
        fade = qc.content_fade_margin
        any_errors = False

        for line in stderr_output.splitlines():
            m = black_re.search(line)
            if m:
                start, end, dur = float(m.group(1)), float(m.group(2)), float(m.group(3))
                if not (start < fade or end > (total_duration - fade)):
                    findings.append(self._finding(
                        passed=False, severity="error",
                        message=f"Black glitch detected in middle: {start}s to {end}s",
                        details={"start": start, "end": end, "duration": dur},
                    ))
                    any_errors = True

            m = freeze_re.search(line)
            if m:
                start, end, dur = float(m.group(1)), float(m.group(2)), float(m.group(3))
                if not (start < fade or end > (total_duration - fade)):
                    findings.append(self._finding(
                        passed=False, severity="error",
                        message=f"Frozen glitch detected in middle: {start}s to {end}s",
                        details={"start": start, "end": end, "duration": dur},
                    ))
                    any_errors = True

        if not any_errors:
            findings.append(self._finding(passed=True, severity="info", message="No black or freeze glitches detected."))

        return findings
