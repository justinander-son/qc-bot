# tests/test_checkers_metadata.py
import shutil
import pytest
from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def test_valid_filename_passes(mock_config, valid_mp4, named_copy):
    fp = named_copy(valid_mp4, "001_Test_T_QRes_v260101a.mp4")
    from checkers.metadata import MetadataChecker
    checker = MetadataChecker(mock_config)
    findings = checker.run(fp)
    filename_f = next(
        f for f in findings
        if "Filename" in f.message or "naming" in f.message.lower() or "convention" in f.message.lower()
    )
    assert filename_f.passed


def test_invalid_filename_fails(mock_config, valid_mp4, named_copy):
    fp = named_copy(valid_mp4, "bad file name.mp4")
    from checkers.metadata import MetadataChecker
    checker = MetadataChecker(mock_config)
    findings = checker.run(fp)
    filename_f = next(
        f for f in findings
        if not f.passed and f.severity == "error" and (
            "ilename" in f.message
            or "naming" in f.message.lower()
            or "convention" in f.message.lower()
        )
    )
    assert not filename_f.passed


def test_correct_resolution_passes(mock_config, valid_mp4, named_copy):
    fp = named_copy(valid_mp4, "001_Test_T_QRes_v260101a.mp4")
    from checkers.metadata import MetadataChecker
    findings = MetadataChecker(mock_config).run(fp)
    res_findings = [
        f for f in findings
        if "Resolution" in f.message or "resolution" in f.message.lower()
    ]
    assert any(f.passed for f in res_findings)


def test_wrong_resolution_fails(mock_config, wrong_res_mp4, named_copy):
    fp = named_copy(wrong_res_mp4, "001_Test_T_QRes_v260101a.mp4")
    from checkers.metadata import MetadataChecker
    findings = MetadataChecker(mock_config).run(fp)
    res_findings = [f for f in findings if "esolution" in f.message]
    assert any(not f.passed for f in res_findings)


def test_wrong_fps_fails(mock_config, wrong_fps_mp4, named_copy):
    fp = named_copy(wrong_fps_mp4, "001_Test_T_QRes_v260101a.mp4")
    from checkers.metadata import MetadataChecker
    findings = MetadataChecker(mock_config).run(fp)
    fps_findings = [
        f for f in findings
        if "ramerate" in f.message or "fps" in f.message.lower()
    ]
    assert any(not f.passed for f in fps_findings)


def test_no_audio_is_warning(mock_config, silent_mp4, named_copy):
    fp = named_copy(silent_mp4, "001_Test_T_QRes_v260101a.mp4")
    from checkers.metadata import MetadataChecker
    findings = MetadataChecker(mock_config).run(fp)
    audio_findings = [f for f in findings if "audio" in f.message.lower()]
    assert any(f.severity == "warning" and f.passed for f in audio_findings)


def test_image_skips_fps(mock_config, valid_png, named_copy):
    fp = named_copy(valid_png, "001_Test_T_QRes_v260101a_01.png")
    from checkers.metadata import MetadataChecker
    findings = MetadataChecker(mock_config).run(fp)
    # Only flag non-passing findings — the checker emits an info "skipped" message for images
    fps_errors = [
        f for f in findings
        if ("ramerate" in f.message or "fps" in f.message.lower()) and not f.passed
    ]
    assert len(fps_errors) == 0
