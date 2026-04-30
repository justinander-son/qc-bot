import subprocess
import re
from pathlib import Path
import config


def run_content_qc(file_path: Path, total_duration: float = None) -> tuple[bool, list[str]]:
    """
    Runs ffmpeg to detect black frames and frozen (duplicate) frames.
    Ignores hits that occur during start/end fades based on config.CONTENT_FADE_MARGIN.
    """
    errors = []
    
    # If duration wasn't passed, we can't reliably ignore end-fades, 
    # but we'll try to get it if needed.
    if total_duration is None:
        total_duration = 999999.0 # Default to huge if unknown

    # Construct filters with high sensitivity (0.03s catches a single frame at 30fps)
    black_filter = f"blackdetect=d={config.BLACK_SENSITIVITY_DURATION}:pix_th={config.BLACK_PIXEL_THRESHOLD}:pic_th={config.BLACK_PICTURE_THRESHOLD}"
    freeze_filter = f"freezedetect=n={config.FREEZE_NOISE_FLOOR}:d={config.FREEZE_SENSITIVITY_DURATION}"
    
    filters = f"{black_filter},{freeze_filter}"

    command = [
        "ffmpeg",
        "-v", "info",
        "-i", str(file_path),
        "-vf", filters,
        "-f", "null",
        "-"
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True)
        stderr_output = result.stderr

        # Regex to capture start, end, and duration of glitches
        # Example: [blackdetect @ ...] black_start:0 black_end:0.5 black_duration:0.5
        black_regex = re.compile(r"black_start:([\d\.]+) black_end:([\d\.]+) black_duration:([\d\.]+)")
        # Example: [freezedetect @ ...] freeze_start:10.5 freeze_end:10.6 freeze_duration:0.1
        freeze_regex = re.compile(r"freeze_start:([\d\.]+) freeze_end:([\d\.]+) freeze_duration:([\d\.]+)")

        for line in stderr_output.splitlines():
            # Check Black Frames
            black_match = black_regex.search(line)
            if black_match:
                start = float(black_match.group(1))
                end = float(black_match.group(2))
                
                # Logic: Ignore if it's within the start margin OR within the end margin
                is_start_fade = start < config.CONTENT_FADE_MARGIN
                is_end_fade = end > (total_duration - config.CONTENT_FADE_MARGIN)
                
                if not (is_start_fade or is_end_fade):
                    errors.append(f"Black glitch detected in middle: {start}s to {end}s")

            # Check Frozen Frames
            freeze_match = freeze_regex.search(line)
            if freeze_match:
                start = float(freeze_match.group(1))
                end = float(freeze_match.group(2))
                
                is_start_fade = start < config.CONTENT_FADE_MARGIN
                is_end_fade = end > (total_duration - config.CONTENT_FADE_MARGIN)
                
                if not (is_start_fade or is_end_fade):
                    errors.append(f"Frozen glitch detected in middle: {start}s to {end}s")

    except Exception as e:
        errors.append(f"FFmpeg content check failed: {e}")

    passed = len(errors) == 0
    return passed, errors
