import subprocess
import json
from pathlib import Path
import config


def check_filename(filename: str) -> tuple[bool, str]:
    """Checks if the filename matches the required convention using the centralized parser."""
    meta = config.parse_metadata(filename)
    if not meta:
        return False, f"Filename '{filename}' does not match naming convention or contains invalid suffixes."
    return True, "Passed"


def get_ffprobe_data(file_path: str) -> dict:
    """Runs ffprobe and returns the metadata as a JSON dictionary."""
    command = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        return {"error": f"ffprobe failed: {e}"}


def run_metadata_qc(file_path: Path) -> tuple[bool, list[str], list[str], str, str]:
    """
    Runs all Phase 1 checks.
    """
    errors = []
    warnings = []
    file_name = file_path.name

    # 1. Filename Check
    valid_name, name_msg = check_filename(file_name)
    if not valid_name:
        errors.append(name_msg)

    # 2. Extract Metadata
    probe_data = get_ffprobe_data(str(file_path))
    if "error" in probe_data:
        errors.append(probe_data["error"])
        return False, errors, warnings, "0.0", "Unknown"

    video_stream = next((s for s in probe_data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in probe_data.get("streams", []) if s.get("codec_type") == "audio"), None)

    if not video_stream:
        errors.append("No video stream found in file.")
        return False, errors, warnings, "0.0", "Unknown"

    # 3. Resolution Info
    width = video_stream.get("width")
    height = video_stream.get("height")
    actual_resolution = f"{width}x{height}"

    # 4. Codec Check
    codec = video_stream.get("codec_name", "")
    if codec not in config.ALLOWED_CODECS:
        errors.append(f"Codec '{codec}' is not allowed: {config.ALLOWED_CODECS}")

    # 5. Resolution Check
    if actual_resolution not in config.ALLOWED_RESOLUTIONS:
        errors.append(f"Resolution '{actual_resolution}' is not allowed: {config.ALLOWED_RESOLUTIONS}")

    # 6. Type-Specific Checks (Images vs Videos)
    is_image = file_name.lower().endswith((".jpg", ".png")) or codec in ["mjpeg", "png"]
    
    if is_image:
        # Images don't have framerate or audio requirements
        pass
    else:
        fps = video_stream.get("r_frame_rate")
        if fps != config.TARGET_FPS:
            errors.append(f"Framerate '{fps}' does not match target '{config.TARGET_FPS}'.")

        if not audio_stream:
            warnings.append("No audio stream found.")

    # 7. Duration
    format_info = probe_data.get("format", {})
    duration = format_info.get("duration", "0.0")

    passed = len(errors) == 0
    return passed, errors, warnings, duration, actual_resolution
