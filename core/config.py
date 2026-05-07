from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class AirtableConfig:
    base_id: str
    table_id: str
    fields: dict[str, str]
    pending_value: str
    status_values: dict[str, str] = field(default_factory=lambda: {
        "pass": "pass",
        "fail": "fail",
        "error": "error",
    })


@dataclass
class QCParams:
    content_fade_margin: float
    black_sensitivity_duration: float
    black_pixel_threshold: float
    black_picture_threshold: float
    freeze_sensitivity_duration: float
    freeze_noise_floor: str
    loudness_target_lufs: float
    loudness_tolerance_lu: float


@dataclass
class ProjectConfig:
    project_name: str
    source_dir: Path
    approved_dir: Path
    db_path: Path
    pipeline_version: str
    filename_regex: str
    allowed_resolutions: list[str]
    allowed_codecs: list[str]
    target_fps: str
    num_workers: int
    airtable: AirtableConfig | None
    qc: QCParams


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(value: Any, strict: bool = True) -> Any:
    """Recursively replace ${VAR_NAME} in strings with environment variable values.

    When strict=False, unresolved variables are left as-is rather than raising.
    Used for optional config sections (e.g. airtable) that may not be configured.
    """
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            resolved = os.environ.get(var_name)
            if resolved is None:
                if strict:
                    raise ValueError(
                        f"Environment variable '{var_name}' is referenced in the project YAML "
                        f"but is not set. Add it to your .env file or shell environment."
                    )
                return match.group(0)  # leave ${VAR} intact
            return resolved
        return _ENV_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v, strict=strict) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(item, strict=strict) for item in value]
    return value


def _read_pipeline_version() -> str:
    version_from_env = os.environ.get("QC_VERSION")
    if version_from_env:
        return version_from_env
    version_file = _PROJECT_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "2.0.0"


def _parse_airtable(raw: dict) -> AirtableConfig:
    default_status = {"pass": "pass", "fail": "fail", "error": "error"}
    return AirtableConfig(
        base_id=raw["base_id"],
        table_id=raw["table_id"],
        fields=raw.get("fields", {}),
        pending_value=raw.get("pending_value", "Pending"),
        status_values={**default_status, **raw.get("status_values", {})},
    )


def _parse_qc(raw: dict) -> QCParams:
    return QCParams(
        content_fade_margin=float(raw["content_fade_margin"]),
        black_sensitivity_duration=float(raw["black_sensitivity_duration"]),
        black_pixel_threshold=float(raw["black_pixel_threshold"]),
        black_picture_threshold=float(raw["black_picture_threshold"]),
        freeze_sensitivity_duration=float(raw["freeze_sensitivity_duration"]),
        freeze_noise_floor=str(raw["freeze_noise_floor"]),
        loudness_target_lufs=float(raw["loudness_target_lufs"]),
        loudness_tolerance_lu=float(raw["loudness_tolerance_lu"]),
    )


def load_config(project: str | None = None) -> ProjectConfig:
    """Load project configuration from .env and projects/{project}.yaml.

    Args:
        project: Project name. Falls back to QC_PROJECT env var, then 'matisse'.

    Returns:
        Fully-resolved ProjectConfig with all env vars substituted.

    Raises:
        FileNotFoundError: If the project YAML does not exist.
        ValueError: If a required env var referenced in the YAML is not set.
    """
    load_dotenv(_PROJECT_ROOT / ".env")

    project_name = project or os.environ.get("QC_PROJECT", "matisse")
    yaml_path = _PROJECT_ROOT / "projects" / f"{project_name}.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Project config not found: {yaml_path}\n"
            f"Expected a YAML file at projects/{project_name}.yaml"
        )

    with yaml_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    # Substitute required fields strictly; keep airtable section non-strict
    # so the pipeline works without Airtable credentials configured.
    airtable_raw_unresolved = raw.pop("airtable", None)
    raw = _substitute_env_vars(raw, strict=True)

    db_url_env = os.environ.get("QC_DATABASE_URL")
    if db_url_env and db_url_env.startswith("sqlite:///"):
        db_path = Path(db_url_env.removeprefix("sqlite:///"))
        if not db_path.is_absolute():
            db_path = _PROJECT_ROOT / db_path
    else:
        db_path = _PROJECT_ROOT / "qc.db"

    airtable: AirtableConfig | None = None
    if airtable_raw_unresolved:
        resolved_airtable = _substitute_env_vars(airtable_raw_unresolved, strict=False)
        # Only build AirtableConfig if all required vars resolved (no ${...} left).
        has_unresolved = any(
            _ENV_PATTERN.search(str(v))
            for v in [resolved_airtable.get("base_id", ""), resolved_airtable.get("table_id", "")]
        )
        if not has_unresolved:
            airtable = _parse_airtable(resolved_airtable)

    num_workers_default = min(4, os.cpu_count() or 2)

    return ProjectConfig(
        project_name=project_name,
        source_dir=Path(raw["source_dir"]),
        approved_dir=Path(raw["approved_dir"]),
        db_path=db_path,
        pipeline_version=_read_pipeline_version(),
        filename_regex=raw["filename_regex"],
        allowed_resolutions=list(raw["allowed_resolutions"]),
        allowed_codecs=list(raw["allowed_codecs"]),
        target_fps=str(raw["target_fps"]),
        num_workers=int(raw.get("num_workers", num_workers_default)),
        airtable=airtable,
        qc=_parse_qc(raw["qc"]),
    )
