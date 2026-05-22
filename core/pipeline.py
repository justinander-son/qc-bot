from __future__ import annotations

import logging
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from core.config import ProjectConfig, load_config
from core.database import Check, has_passed, init_db, get_session, save_result, create_run, finalise_run, recompute_run_stats
from core.models import JobSummary, QCResult
from checkers.base import CheckFinding

logger = logging.getLogger(__name__)

_PIPELINE_VERSION_DEFAULT = "2.0.0"

# Checkers run in this order for every file. Image files skip the video-only checkers
# inside each checker's own run() method — no need to gate them here.
_CHECKER_ORDER = ["metadata", "integrity", "content", "colorspace"]

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
_MEDIA_EXTS = {".mp4", ".mov", ".jpg", ".jpeg", ".png"}

# Sentinel directory used when an Airtable path cannot be resolved locally.
# process_file detects this and short-circuits all checkers.
_MISSING_SENTINEL = Path("/__missing__")


def _import_all_checkers() -> None:
    """Import checker modules so their @register decorators fire."""
    import checkers.metadata   # noqa: F401
    import checkers.integrity  # noqa: F401
    import checkers.content    # noqa: F401
    import checkers.colorspace # noqa: F401


def _extract_media_meta(findings: list[CheckFinding]) -> tuple[str, str, str | None, int | None]:
    """Walk findings to extract duration, actual_res, bitrate_mbps, and frame_count."""
    duration = "0.0"
    actual_res = "Unknown"
    bitrate_mbps = None
    frame_count = None
    for f in findings:
        if "duration" in f.details:
            duration = str(f.details["duration"])
        if "actual_res" in f.details:
            actual_res = str(f.details["actual_res"])
        if "bitrate_mbps" in f.details and f.details["bitrate_mbps"] is not None:
            bitrate_mbps = str(f.details["bitrate_mbps"])
        if "frame_count" in f.details and f.details["frame_count"] is not None:
            frame_count = int(f.details["frame_count"])
    return duration, actual_res, bitrate_mbps, frame_count


def _parse_meta(filename: str, config: ProjectConfig) -> dict:
    """Parse shot metadata from filename using the project regex."""
    pattern = config.filename_regex
    m = re.match(pattern, filename)
    if not m:
        return {}
    groups = m.groups()
    keys = ["shot", "name", "uv_area", "res_name", "version", "frame", "ext"]
    return {k: v for k, v in zip(keys, groups)}


def _get_routing_path(filename: str, config: ProjectConfig) -> Optional[Path]:
    """Derive the destination path under approved_dir using shot-folder conventions."""
    meta = _parse_meta(filename, config)
    if not meta:
        return None
    try:
        shot_str = meta["shot"]
        chapter_num = (int(shot_str) // 100) * 100
        chapter_str = f"{chapter_num:03d}"
        return config.approved_dir / chapter_str / shot_str / filename
    except Exception:
        return None


def process_file(
    file_path: Path,
    record_id: Optional[str],
    config: ProjectConfig,
    db_lock: threading.Lock,
    db_url: Optional[str],
    run_id: Optional[str] = None,
) -> QCResult:
    """Run all checkers on a single file and return a QCResult.

    db_lock and db_url are passed so this can be called from threads safely.
    """
    from core.registry import get_checker

    checked_at = datetime.now(timezone.utc)

    # Unresolvable Airtable path — skip all checkers and return a clean error.
    if file_path.is_relative_to(_MISSING_SENTINEL):
        try:
            rel_path_str = str(file_path.relative_to(config.source_dir))
        except ValueError:
            rel_path_str = record_id or file_path.name
        result = QCResult(
            filename=file_path.name,
            rel_path=rel_path_str,
            file_path=file_path,
            airtable_record_id=record_id,
            run_id=run_id,
            status="error",
            findings=[CheckFinding(
                checker="pipeline",
                passed=False,
                severity="error",
                message=f"Path '{file_path.name}' could not be resolved under source directory. Check the 'Dailies File Path' field in Airtable.",
            )],
            duration="0.0",
            actual_res="Unknown",
            meta={},
            dest_path=None,
            pipeline_version=config.pipeline_version,
            checked_at=checked_at,
        )
        _save_to_db(result, db_lock, db_url)
        return result

    all_findings: list[CheckFinding] = []

    try:
        for name in _CHECKER_ORDER:
            try:
                checker_cls = get_checker(name)
            except KeyError:
                logger.warning("Checker '%s' not registered; skipping.", name)
                continue
            checker = checker_cls(config)
            findings = checker.run(file_path)
            all_findings.extend(findings)
    except Exception as e:
        logger.exception("Unexpected error running checkers on %s", file_path)
        duration, actual_res = "0.0", "Unknown"
        meta = _parse_meta(file_path.name, config)
        try:
            rel_path = str(file_path.relative_to(config.source_dir))
        except ValueError:
            rel_path = file_path.name

        error_finding = CheckFinding(
            checker="pipeline",
            passed=False,
            severity="error",
            message=f"Checker pipeline error: {e}",
        )
        return QCResult(
            filename=file_path.name,
            rel_path=rel_path,
            file_path=file_path,
            airtable_record_id=record_id,
            run_id=run_id,
            status="error",
            findings=[error_finding],
            duration=duration,
            actual_res=actual_res,
            meta=meta,
            dest_path=None,
            pipeline_version=config.pipeline_version,
            checked_at=checked_at,
        )

    duration, actual_res, bitrate_mbps, frame_count = _extract_media_meta(all_findings)

    failed_errors = [
        f for f in all_findings if not f.passed and f.severity == "error"
    ]
    status = "fail" if failed_errors else "pass"

    try:
        rel_path = str(file_path.relative_to(config.source_dir))
    except ValueError:
        rel_path = file_path.name

    meta = _parse_meta(file_path.name, config)
    if meta:
        meta["actual_res"] = actual_res
        meta["rel_path"] = rel_path
        meta["duration"] = duration
        if frame_count is not None:
            meta["frame_count"] = frame_count
        if bitrate_mbps is not None:
            meta["bitrate_mbps"] = bitrate_mbps
    else:
        meta = {"actual_res": actual_res, "rel_path": rel_path, "duration": duration}
        if frame_count is not None:
            meta["frame_count"] = frame_count
        if bitrate_mbps is not None:
            meta["bitrate_mbps"] = bitrate_mbps

    dest_path: Optional[Path] = None
    if status == "pass":
        dest_path = _get_routing_path(file_path.name, config)
        if dest_path:
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest_path)
            except Exception:
                logger.exception("Failed to copy %s to %s", file_path, dest_path)
                dest_path = None

    result = QCResult(
        filename=file_path.name,
        rel_path=rel_path,
        file_path=file_path,
        airtable_record_id=record_id,
        run_id=run_id,
        status=status,
        findings=all_findings,
        duration=duration,
        actual_res=actual_res,
        meta=meta,
        dest_path=dest_path,
        pipeline_version=config.pipeline_version,
        checked_at=checked_at,
    )

    _save_to_db(result, db_lock, db_url)
    return result


def _save_to_db(result: QCResult, lock: threading.Lock, db_url: Optional[str]) -> None:
    """Write a QCResult to SQLite under a threading lock."""
    with lock:
        try:
            with get_session(db_url) as session:
                db_result = save_result(session, {
                    "run_id": result.run_id,
                    "filename": result.filename,
                    "rel_path": result.rel_path,
                    "status": result.status,
                    "pipeline_version": result.pipeline_version,
                    "checked_at": result.checked_at,
                    "meta": result.meta,
                    "airtable_record_id": result.airtable_record_id,
                    "airtable_synced": False,
                })

                for finding in result.findings:
                    db_check = Check(
                        result_id=db_result.id,
                        checker=finding.checker,
                        passed=finding.passed,
                        severity=finding.severity,
                        message=finding.message,
                        details=finding.details,
                    )
                    session.add(db_check)
        except Exception:
            logger.exception("DB write failed for %s", result.rel_path)


_THRU_RE = re.compile(r'^(.+)_(\d+)thru(\d+)$', re.IGNORECASE)


def _parse_thru(name: str) -> Optional[tuple[str, int, int, int]]:
    """Parse 'base_NNthruNN'. Returns (base, start, end, zero_pad_width) or None."""
    stem = Path(name).stem if "." in name else name
    m = _THRU_RE.match(stem)
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3)), len(m.group(2))


def _expand_thru_range(base: str, start: int, end: int, width: int, search_dir: Path) -> list[Path]:
    """Return all files matching base_NN.* for frame in [start, end]."""
    files: list[Path] = []
    for frame in range(start, end + 1):
        frame_str = str(frame).zfill(width)
        for f in search_dir.rglob(f"{base}_{frame_str}.*"):
            if f.is_file() and f.suffix.lower() in _MEDIA_EXTS:
                files.append(f)
    return files


def _expand_to_files(path: Path) -> list[Path]:
    """Return media files: the file itself, or all media files if path is a directory."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return [
            f for f in path.rglob("*")
            if f.is_file() and f.suffix.lower() in _MEDIA_EXTS and not f.name.startswith(".")
        ]
    return []


def _resolve_airtable_paths(raw_path: str, config: ProjectConfig) -> list[Path]:
    """Resolve a raw Airtable path string to one or more local Paths.

    Handles four forms observed in production:
    1. Absolute path to a specific file (possibly from a different machine)
    2. //relative/path  →  resolved against source_dir; may be a directory
    3. Directory path   →  expanded to all media files within
    4. Frame range      →  basename_NNthruNN expands to N individual files
    """
    search_dir = config.source_dir

    if raw_path.startswith("//"):
        rel = Path(raw_path.lstrip("/"))
        parts = rel.parts
        # Progressive suffix walk — strip leading components one at a time until a
        # local match is found. Handles source_dir already containing the leading
        # segments of the stored path (e.g. source_dir ends in "03_Animator Dailies"
        # but the stored path starts with "//03_Animator Dailies/…").
        for i in range(len(parts)):
            candidate = config.source_dir / Path(*parts[i:])
            if candidate.exists():
                return _expand_to_files(candidate)
        # Nothing matched — fall through to thru/rglob with leaf name
        leaf = rel.name
    else:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            if candidate.exists():
                return _expand_to_files(candidate)
            # Cross-machine: walk parts right-to-left looking for a local match
            parts = candidate.parts
            for i in range(1, len(parts)):
                local = config.source_dir / Path(*parts[i:])
                if local.exists():
                    return _expand_to_files(local)
            leaf = candidate.name
        else:
            local = config.source_dir / candidate
            if local.exists():
                return _expand_to_files(local)
            leaf = Path(raw_path).name

    # Check for frame range notation (e.g. v260430a_01thru09)
    thru = _parse_thru(leaf)
    if thru:
        base, start, end, width = thru
        files = _expand_thru_range(base, start, end, width, search_dir)
        if files:
            return files

    # Last resort: rglob by leaf name, but only for files (not directories —
    # matching a bare folder name like "LH" across wrong date folders is too broad)
    if "." in leaf:
        matches = list(search_dir.rglob(leaf))
        return [matches[0]] if matches else []

    return []


def _build_file_list_from_airtable(
    pending: list[dict],
    config: ProjectConfig,
    db_url: Optional[str] = None,
) -> list[tuple[Path, Optional[str], str]]:
    """Resolve Airtable records to (file_path, record_id, rel_path) tuples.

    Airtable is the authoritative job queue — every record returned by
    get_pending_records() is processed unconditionally. Skipping by local DB
    status would prevent re-QC when a record is moved back to pending.
    Unresolvable paths produce a sentinel entry so the record still gets an
    error status written back to Airtable.
    """
    resolved: list[tuple[Path, Optional[str], str]] = []

    for rec in pending:
        record_id: str = rec["record_id"]
        raw_path: Optional[str] = rec.get("file_path")

        if not raw_path:
            logger.warning("Record %s has no file_path; skipping.", record_id)
            continue

        raw_path = raw_path.strip().strip("'\"")

        files = _resolve_airtable_paths(raw_path, config)

        if not files:
            logger.warning(
                "Path '%s' from record %s could not be resolved under %s.",
                raw_path, record_id, config.source_dir,
            )
            resolved.append((_MISSING_SENTINEL / Path(raw_path).name, record_id, raw_path))
            continue

        for file_path in files:
            try:
                rel_path = str(file_path.relative_to(config.source_dir))
            except ValueError:
                rel_path = file_path.name
            resolved.append((file_path, record_id, rel_path))

    return resolved




def _build_file_list_from_scan(
    config: ProjectConfig,
    db_url: Optional[str],
) -> list[tuple[Path, Optional[str], str]]:
    """Directory-scan fallback used when Airtable is not configured."""
    resolved: list[tuple[Path, Optional[str], str]] = []

    with get_session(db_url) as session:
        for file_path in config.source_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.name.startswith("."):
                continue

            try:
                rel_path = str(file_path.relative_to(config.source_dir))
            except ValueError:
                rel_path = file_path.name

            if has_passed(session, rel_path):
                continue

            resolved.append((file_path, None, rel_path))

    return resolved


def run_pipeline(
    project: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    retry_run_id: Optional[str] = None,
) -> JobSummary:
    """Main entry point for the Phase 2 pipeline.

    If Airtable is configured, pulls pending records and drives processing from
    those. Otherwise falls back to directory scan (Phase 1 behaviour).
    Returns a JobSummary.
    """
    _import_all_checkers()

    config = load_config(project)
    db_url = str(config.db_path) if config.db_path else None
    if db_url and not db_url.startswith("sqlite:///"):
        db_url = f"sqlite:///{config.db_path}"

    init_db(db_url)

    if retry_run_id:
        run_id: str = retry_run_id
        from core.database import Run
        from sqlalchemy import select as _select
        with get_session(db_url) as session:
            existing = session.execute(_select(Run).where(Run.id == retry_run_id)).scalar_one_or_none()
            started_at = existing.started_at if existing else datetime.now(timezone.utc)
    else:
        started_at = datetime.now(timezone.utc)
        with get_session(db_url) as session:
            run = create_run(session, config.project_name, started_at)
            run_id = run.id

    summary = JobSummary(
        project=config.project_name,
        started_at=started_at,
        completed_at=None,
        total=0,
        passed=0,
        failed=0,
        skipped=0,
        errors=0,
    )

    integrations = _build_integrations(config, db_url=db_url)

    for integration in integrations:
        integration.on_job_start(summary)

    if config.airtable is not None:
        from integrations.airtable import AirtableIntegration
        airtable_integration = next(
            (i for i in integrations if isinstance(i, AirtableIntegration)), None
        )
        pending = (
            airtable_integration.get_pending_records()
            if airtable_integration
            else []
        )
        work_items = _build_file_list_from_airtable(pending, config)
    else:
        work_items = _build_file_list_from_scan(config, db_url)

    total_count = len(work_items)
    summary.total = total_count

    if total_count == 0:
        summary.completed_at = datetime.now(timezone.utc)
        if retry_run_id:
            _recompute_run(run_id, db_url)
        else:
            _finalise_run(run_id, summary, db_url)
        print(">> PROGRESS: 100")
        for integration in integrations:
            integration.on_job_complete(summary, [])
        return summary

    db_lock = threading.Lock()
    results: list[QCResult] = []
    processed_count = 0

    with ThreadPoolExecutor(max_workers=config.num_workers) as executor:
        future_to_item = {
            executor.submit(
                process_file,
                file_path,
                record_id,
                config,
                db_lock,
                db_url,
                run_id,
            ): (file_path, record_id, rel_path)
            for file_path, record_id, rel_path in work_items
        }

        for future in as_completed(future_to_item):
            processed_count += 1
            progress_pct = int((processed_count / total_count) * 100)
            print(f">> PROGRESS: {progress_pct}", flush=True)

            try:
                result = future.result()
            except Exception as e:
                file_path, record_id, rel_path = future_to_item[future]
                logger.exception("process_file raised for %s", file_path)
                result = QCResult(
                    filename=Path(rel_path).name,
                    rel_path=rel_path,
                    file_path=file_path,
                    airtable_record_id=record_id,
                    run_id=run_id,
                    status="error",
                    findings=[CheckFinding(
                        checker="pipeline",
                        passed=False,
                        severity="error",
                        message=f"Unhandled pipeline exception: {e}",
                    )],
                    duration="0.0",
                    actual_res="Unknown",
                    meta={},
                    dest_path=None,
                    pipeline_version=config.pipeline_version,
                    checked_at=datetime.now(timezone.utc),
                )

            results.append(result)

            if progress_callback:
                progress_callback(processed_count, total_count)

            if result.status == "pass":
                summary.passed += 1
            elif result.status == "fail":
                summary.failed += 1
            elif result.status == "skipped":
                summary.skipped += 1
            else:
                summary.errors += 1

            for integration in integrations:
                integration.on_record_complete(result)

    summary.completed_at = datetime.now(timezone.utc)
    if retry_run_id:
        _recompute_run(run_id, db_url)
    else:
        _finalise_run(run_id, summary, db_url)

    for integration in integrations:
        integration.on_job_complete(summary, results)

    return summary


def _recompute_run(run_id: str, db_url: Optional[str]) -> None:
    """Recompute a Run's stats from the DB — used after a retry."""
    try:
        with get_session(db_url) as session:
            recompute_run_stats(session, run_id)
    except Exception:
        logger.exception("Failed to recompute stats for run %s", run_id)


def _finalise_run(run_id: str, summary: JobSummary, db_url: Optional[str]) -> None:
    try:
        with get_session(db_url) as session:
            finalise_run(session, run_id, {
                "completed_at": summary.completed_at,
                "total": summary.total,
                "passed": summary.passed,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "errors": summary.errors,
            })
    except Exception:
        logger.exception("Failed to finalise run %s", run_id)


def _build_integrations(config: ProjectConfig, db_url: Optional[str] = None) -> list:
    """Construct the active integration list based on config and env vars."""
    from integrations.airtable import AirtableIntegration
    from integrations.notifications import SlackNotification

    integrations = []

    if config.airtable is not None:
        integrations.append(AirtableIntegration(config.airtable, db_url=db_url))

    slack_url = os.environ.get("SLACK_WEBHOOK_URL")
    if slack_url:
        integrations.append(SlackNotification(slack_url))

    return integrations
