from __future__ import annotations

import re
import subprocess
from pathlib import Path

from checkers.base import BaseChecker, CheckFinding
from core.registry import register

_LUFS_RE = re.compile(r"I:\s+([-\d.]+)\s+LUFS")
_PEAK_RE = re.compile(r"Peak:\s+([-\d.]+)\s+dBTP")
_TRUE_PEAK_MAX = -1.0


def _get_loudness_params(config) -> tuple[float, float]:
    qc = getattr(config, "qc", None)
    if qc is not None:
        target = getattr(qc, "loudness_target_lufs", -23.0)
        tolerance = getattr(qc, "loudness_tolerance_lu", 1.0)
        return float(target), float(tolerance)
    target = getattr(config, "loudness_target_lufs", -23.0)
    tolerance = getattr(config, "loudness_tolerance_lu", 1.0)
    return float(target), float(tolerance)


@register("loudness")
class LoudnessChecker(BaseChecker):
    def run(self, file_path: Path) -> list[CheckFinding]:
        if file_path.suffix.lower() in (".jpg", ".png"):
            return [self._finding(passed=True, severity="info", message="Image file; loudness check skipped.")]

        target_lufs, tolerance_lu = _get_loudness_params(self._config)

        command = [
            "ffmpeg",
            "-i", str(file_path),
            "-af", "ebur128=peak=true",
            "-f", "null",
            "-",
        ]

        try:
            result = subprocess.run(command, capture_output=True, text=True)
            stderr = result.stderr
        except Exception as e:
            return [self._finding(
                passed=False,
                severity="error",
                message=f"FFmpeg loudness check failed: {e}",
            )]

        lufs_match = _LUFS_RE.search(stderr)
        peak_match = _PEAK_RE.search(stderr)

        if not lufs_match:
            # No loudness output means no audio stream — optional for dailies.
            return [self._finding(
                passed=True,
                severity="warning",
                message="No audio stream detected; loudness check skipped.",
            )]

        integrated_lufs = float(lufs_match.group(1))
        true_peak_dbtp = float(peak_match.group(1)) if peak_match else None

        findings: list[CheckFinding] = []

        lower_bound = target_lufs - tolerance_lu
        upper_bound = target_lufs + tolerance_lu
        loudness_ok = lower_bound <= integrated_lufs <= upper_bound

        base_details: dict = {
            "integrated_lufs": integrated_lufs,
            "target_lufs": target_lufs,
            "tolerance_lu": tolerance_lu,
        }
        if true_peak_dbtp is not None:
            base_details["true_peak_dbtp"] = true_peak_dbtp

        if loudness_ok:
            findings.append(self._finding(
                passed=True,
                severity="info",
                message=f"Integrated loudness {integrated_lufs:.1f} LUFS is within target {target_lufs:.1f} ±{tolerance_lu:.1f} LU.",
                details=base_details,
            ))
        else:
            findings.append(self._finding(
                passed=False,
                severity="error",
                message=(
                    f"Integrated loudness {integrated_lufs:.1f} LUFS is outside target "
                    f"{target_lufs:.1f} ±{tolerance_lu:.1f} LU "
                    f"(acceptable range: {lower_bound:.1f}–{upper_bound:.1f} LUFS)."
                ),
                details=base_details,
            ))

        if true_peak_dbtp is not None and true_peak_dbtp > _TRUE_PEAK_MAX:
            findings.append(self._finding(
                passed=False,
                severity="error",
                message=(
                    f"True peak {true_peak_dbtp:.1f} dBTP exceeds maximum {_TRUE_PEAK_MAX:.1f} dBTP."
                ),
                details=base_details,
            ))
        elif true_peak_dbtp is not None:
            findings.append(self._finding(
                passed=True,
                severity="info",
                message=f"True peak {true_peak_dbtp:.1f} dBTP is within limit.",
                details=base_details,
            ))

        return findings
