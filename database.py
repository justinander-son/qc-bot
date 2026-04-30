# database.py
import json
import threading
from pathlib import Path
from datetime import datetime

# Global lock to ensure thread-safety when multiple workers write to the JSON file
db_lock = threading.Lock()

def load_db(db_path: Path) -> dict:
    """Loads the JSON database, or returns an empty dict if it doesn't exist."""
    if not db_path.exists():
        return {}

    try:
        with open(db_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_db(db_path: Path, data: dict):
    """Saves the dictionary back to the JSON file with nice formatting."""
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def has_file_passed(db_path: Path, filename: str) -> bool:
    """Checks if a file is in the database AND has previously passed."""
    with db_lock:
        db = load_db(db_path)
        if filename in db:
            status = db[filename].get("status", "fail")
            return status in ["pass", "overridden"]
        return False


def log_result(db_path: Path, filename: str, passed: bool, duration: str, errors: list[str],
               warnings: list[str] = None, status: str = None, meta: dict = None):
    """Logs the QC result for a specific file with thread-safe locking."""
    if warnings is None:
        warnings = []
    if meta is None:
        meta = {}

    with db_lock:
        db = load_db(db_path)

        if status is None:
            status = "pass" if passed else "fail"

        db[filename] = {
            "passed": passed,
            "status": status,
            "duration": duration,
            "errors": errors,
            "warnings": warnings,
            "meta": meta,
            "checked_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        save_db(db_path, db)
