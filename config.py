import re
import os
import shutil
from pathlib import Path

# ==============================================================================
# 1. DIRECTORY SETTINGS
# ==============================================================================
SOURCE_DIR = Path('/Users/justin.anderson/Library/CloudStorage/Dropbox-59Productions/59--Working_Files-Video/Lightroom Matisse/03_Animator Dailies')
APPROVED_DIR = Path('/Users/justin.anderson/Desktop/PyQCTestResults2')
DATABASE_FILE = Path("qc_database.json")

# Folders to completely ignore during the QC scan
EXCLUDED_DIRS = [
    "26-03-04", "26-03-10", "26-03-11", "26-03-12", "26-03-13", 
    "26-03-16", "26-03-17", "26-03-18", "26-03-19", "26-03-20", 
    "26-03-23", "26-03-24", "26-03-25", "26-03-26", "26-03-27", 
    "26-03-30", "26-03-31", "26-04-01", "26-04-02", "26-04-07", 
    "26-04-08", "26-04-09", "26-04-10", "26-04-13", "26-04-14", 
    "26-04-15", "26-04-16", "26-04-20", "26-04-21", "26-04-22", 
    "26-04-23", "26-04-24", "26-04-26", "26-04-27", "26-04-28",
    "26-04-29", "26-04-30", "26-05-01"
]

def is_path_excluded(file_path):
    """Checks if any part of the file path contains an excluded directory name."""
    parts = Path(file_path).parts
    for excluded in EXCLUDED_DIRS:
        if excluded in parts:
            return True
    return False

# ==============================================================================
# 2. FILENAME LOGIC (The Core "Source of Truth")
# ==============================================================================
FILENAME_REGEX = re.compile(r"^(\d{3})_([A-Za-z0-9]+)_(T|All Walls|Brick|Floor|WallA|WallB|WallC|WallD)_(FullRes|HalfRes|QRes)_(v\d{6}[a-z]?)(?:_(\d+))?\.(mp4|jpg|png)$")

def parse_metadata(filename, strict=True):
    match = FILENAME_REGEX.match(filename)
    if match:
        meta = {
            "shot": match.group(1),
            "name": match.group(2),
            "uv_area": match.group(3),
            "res_name": match.group(4),
            "version": match.group(5),
            "frame": match.group(6),
            "ext": match.group(7)
        }
        if meta["frame"] and meta["ext"] == "mp4":
            if strict: return None
        return meta
    
    if not strict:
        try:
            parts = Path(filename).stem.split('_')
            return {
                "shot": parts[0],
                "name": "Unknown",
                "uv_area": "Unknown",
                "res_name": "Unknown",
                "version": parts[-1].split('_')[0],
                "frame": parts[-1].split('_')[1] if len(parts[-1].split('_')) > 1 else None,
                "ext": Path(filename).suffix[1:]
            }
        except:
            return None
    return None

def get_routing_path(filename, strict=True):
    """Determines the Approved folder structure."""
    meta = parse_metadata(filename, strict=strict)
    if not meta: return None
    try:
        shot_str = meta["shot"]
        chapter_num = (int(shot_str) // 100) * 100
        chapter_str = f"{chapter_num:03d}"
        return APPROVED_DIR / chapter_str / shot_str / filename
    except:
        return None

# ==============================================================================
# 3. QC PARAMETERS
# ==============================================================================
ALLOWED_RESOLUTIONS = [
    "13584x1712", "6792x2260", "13584x4518", "8192x4320",
    "2318x1632", "4636x3264", "7972x3424", "5612x3424"
]
ALLOWED_CODECS = ["h264", "prores", "mjpeg", "png"]
TARGET_FPS = "30/1"

CONTENT_FADE_MARGIN = 0.5
BLACK_SENSITIVITY_DURATION = 0.03 
BLACK_PIXEL_THRESHOLD = 0.00
BLACK_PICTURE_THRESHOLD = 0.98
FREEZE_SENSITIVITY_DURATION = 0.03
FREEZE_NOISE_FLOOR = "-60dB"

# ==============================================================================
# 4. PERFORMANCE SETTINGS
# ==============================================================================
NUM_WORKERS = min(4, os.cpu_count() or 2)
