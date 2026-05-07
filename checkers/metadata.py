from __future__ import annotations

import re
import subprocess
import json
from pathlib import Path

from checkers.base import BaseChecker, CheckFinding
from core.registry import register


def get_ffprobe_data(file_path: str) -> dict:
    command = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        return {"error": f"ffprobe failed: {e}"}


@register("metadata")
class MetadataChecker(BaseChecker):
    def run(self, file_path: Path) -> list[CheckFinding]:
        findings: list[CheckFinding] = []
        filename = file_path.name

        if not re.match(self._config.filename_regex, filename):
            findings.append(self._finding(
                passed=False,
                severity="error",
                message=f"Filename '{filename}' does not match naming convention.",
            ))
        else:
            findings.append(self._finding(passed=True, severity="info", message="Filename matches convention."))

        probe_data = get_ffprobe_data(str(file_path))
        if "error" in probe_data:
            findings.append(self._finding(passed=False, severity="error", message=probe_data["error"]))
            return findings

        streams = probe_data.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        if not video_stream:
            findings.append(self._finding(passed=False, severity="error", message="No video stream found in file."))
            return findings

        width = video_stream.get("width")
        height = video_stream.get("height")
        actual_resolution = f"{width}x{height}"
        codec = video_stream.get("codec_name", "")
        format_info = probe_data.get("format", {})
        duration = format_info.get("duration", "0.0")

        if codec not in self._config.allowed_codecs:
            findings.append(self._finding(
                passed=False, severity="error",
                message=f"Codec '{codec}' is not allowed: {self._config.allowed_codecs}",
                details={"codec": codec, "allowed_codecs": self._config.allowed_codecs},
            ))
        else:
            findings.append(self._finding(
                passed=True, severity="info",
                message=f"Codec '{codec}' is allowed.",
                details={"codec": codec},
            ))

        if actual_resolution not in self._config.allowed_resolutions:
            findings.append(self._finding(
                passed=False, severity="error",
                message=f"Resolution '{actual_resolution}' is not in allowed list.",
                details={"actual_res": actual_resolution, "allowed_resolutions": self._config.allowed_resolutions},
            ))
        else:
            findings.append(self._finding(
                passed=True, severity="info",
                message=f"Resolution '{actual_resolution}' is allowed.",
                details={"actual_res": actual_resolution},
            ))

        is_image = filename.lower().endswith((".jpg", ".png")) or codec in ["mjpeg", "png"]
        if not is_image:
            fps = video_stream.get("r_frame_rate")
            if fps != self._config.target_fps:
                findings.append(self._finding(
                    passed=False, severity="error",
                    message=f"Framerate '{fps}' does not match target '{self._config.target_fps}'.",
                    details={"fps": fps, "target_fps": self._config.target_fps, "duration": duration, "actual_res": actual_resolution},
                ))
            else:
                findings.append(self._finding(
                    passed=True, severity="info",
                    message=f"Framerate '{fps}' matches target.",
                    details={"fps": fps, "duration": duration, "actual_res": actual_resolution},
                ))

            if not audio_stream:
                findings.append(self._finding(
                    passed=True, severity="warning",
                    message="No audio stream found.",
                    details={"duration": duration, "actual_res": actual_resolution},
                ))
        else:
            findings.append(self._finding(
                passed=True, severity="info",
                message="Image file; framerate and audio checks skipped.",
                details={"duration": duration, "actual_res": actual_resolution},
            ))

        return findings
