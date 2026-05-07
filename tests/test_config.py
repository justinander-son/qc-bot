# tests/test_config.py
import os
import textwrap
import pytest
from pathlib import Path


def test_load_config_missing_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("QC_PROJECT", "nonexistent_project_xyz")
    monkeypatch.setenv("SOURCE_DIR", str(tmp_path))
    monkeypatch.setenv("APPROVED_DIR", str(tmp_path))
    from core.config import load_config
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent_project_xyz")


def test_load_config_missing_required_env_var(tmp_path, monkeypatch):
    # Write a YAML that references an env var that is NOT set
    yaml_dir = tmp_path / "projects"
    yaml_dir.mkdir()
    (yaml_dir / "testshow.yaml").write_text(textwrap.dedent("""
        project: testshow
        source_dir: ${DEFINITELY_NOT_SET_XYZ}
        approved_dir: /tmp
        filename_regex: '^test$'
        allowed_resolutions: []
        allowed_codecs: []
        target_fps: "30/1"
        qc:
          content_fade_margin: 0.5
          black_sensitivity_duration: 0.03
          black_pixel_threshold: 0.10
          black_picture_threshold: 0.98
          freeze_sensitivity_duration: 0.03
          freeze_noise_floor: "-60dB"
          loudness_target_lufs: -23.0
          loudness_tolerance_lu: 1.0
    """))
    monkeypatch.delenv("DEFINITELY_NOT_SET_XYZ", raising=False)
    # Patch _PROJECT_ROOT so load_config finds our temp projects/ dir
    import core.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_PROJECT_ROOT", tmp_path)
    with pytest.raises(ValueError, match="DEFINITELY_NOT_SET_XYZ"):
        cfg_mod.load_config("testshow")


def test_airtable_section_optional(tmp_path, monkeypatch):
    yaml_dir = tmp_path / "projects"
    yaml_dir.mkdir()
    (yaml_dir / "noairtable.yaml").write_text(textwrap.dedent(f"""
        project: noairtable
        source_dir: {tmp_path}
        approved_dir: {tmp_path}
        filename_regex: '^test$'
        allowed_resolutions: []
        allowed_codecs: []
        target_fps: "30/1"
        qc:
          content_fade_margin: 0.5
          black_sensitivity_duration: 0.03
          black_pixel_threshold: 0.10
          black_picture_threshold: 0.98
          freeze_sensitivity_duration: 0.03
          freeze_noise_floor: "-60dB"
          loudness_target_lufs: -23.0
          loudness_tolerance_lu: 1.0
    """))
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    import core.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_PROJECT_ROOT", tmp_path)
    cfg = cfg_mod.load_config("noairtable")
    assert cfg.airtable is None


def test_pipeline_version_from_file(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("9.9.9")
    import core.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("QC_VERSION", raising=False)
    assert cfg_mod._read_pipeline_version() == "9.9.9"


def test_num_workers_in_mock_config(mock_config):
    assert mock_config.num_workers >= 1
