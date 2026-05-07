from __future__ import annotations

from pathlib import Path

from checkers.base import BaseChecker, CheckFinding
from checkers.metadata import get_ffprobe_data
from core.registry import register

_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

_CODEC_EXPECTED_PIX_FMT: dict[str, list[str]] = {
    "h264": ["yuv420p"],
    "prores": ["yuv422p10le", "yuva444p10le"],
}


def _derive_bit_depth(pix_fmt: str) -> int:
    if "12" in pix_fmt:
        return 12
    if "10" in pix_fmt:
        return 10
    return 8


@register("colorspace")
class ColorspaceChecker(BaseChecker):
    def run(self, file_path: Path) -> list[CheckFinding]:
        if file_path.suffix.lower() in (".jpg", ".png"):
            return [self._finding(passed=True, severity="info", message="Image file; colorspace check skipped.")]

        probe_data = get_ffprobe_data(str(file_path))
        if "error" in probe_data:
            return [self._finding(
                passed=False,
                severity="error",
                message=probe_data["error"],
            )]

        video_stream = next(
            (s for s in probe_data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        if not video_stream:
            return [self._finding(
                passed=False,
                severity="error",
                message="No video stream found; colorspace check skipped.",
            )]

        pix_fmt = video_stream.get("pix_fmt", "")
        color_space = video_stream.get("color_space", "")
        color_transfer = video_stream.get("color_transfer", "")
        color_primaries = video_stream.get("color_primaries", "")
        bit_depth = _derive_bit_depth(pix_fmt)

        details: dict = {
            "pix_fmt": pix_fmt,
            "color_space": color_space,
            "color_transfer": color_transfer,
            "color_primaries": color_primaries,
            "bit_depth": bit_depth,
        }

        findings: list[CheckFinding] = []
        codec = video_stream.get("codec_name", "")

        expected_fmts = _CODEC_EXPECTED_PIX_FMT.get(codec)
        if expected_fmts is not None and pix_fmt not in expected_fmts:
            findings.append(self._finding(
                passed=False,
                severity="warning",
                message=(
                    f"Pixel format '{pix_fmt}' is unexpected for codec '{codec}'. "
                    f"Expected one of: {expected_fmts}."
                ),
                details=details,
            ))
        else:
            findings.append(self._finding(
                passed=True,
                severity="info",
                message=f"Pixel format '{pix_fmt}' is acceptable for codec '{codec}'.",
                details=details,
            ))

        if color_transfer in _HDR_TRANSFERS:
            hdr_label = "HDR10 (PQ)" if color_transfer == "smpte2084" else "HLG"
            findings.append(self._finding(
                passed=True,
                severity="info",
                message=f"HDR content detected: {hdr_label} (color_transfer='{color_transfer}').",
                details=details,
            ))

        return findings
