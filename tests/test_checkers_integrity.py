# tests/test_checkers_integrity.py
import shutil
import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def test_empty_file_fails(mock_config, empty_file):
    from checkers.integrity import IntegrityChecker
    findings = IntegrityChecker(mock_config).run(empty_file)
    assert findings[0].passed is False
    assert findings[0].severity == "error"
    assert "0 bytes" in findings[0].message


def test_normal_file_passes_size_check(mock_config, valid_mp4):
    from checkers.integrity import IntegrityChecker
    findings = IntegrityChecker(mock_config).run(valid_mp4)
    size_finding = next(f for f in findings if "bytes" in f.message.lower())
    assert size_finding.passed


def test_image_skips_pts(mock_config, valid_png):
    from checkers.integrity import IntegrityChecker
    findings = IntegrityChecker(mock_config).run(valid_png)
    pts_findings = [
        f for f in findings
        if "PTS" in f.message or "pts" in f.message.lower() or "discontinuity" in f.message.lower()
    ]
    assert len(pts_findings) == 0


def test_clean_video_no_pts_discontinuities(mock_config, valid_mp4):
    from checkers.integrity import IntegrityChecker
    findings = IntegrityChecker(mock_config).run(valid_mp4)
    disc_findings = [
        f for f in findings
        if "discontinuity" in f.message.lower() or "discontinuities" in f.message.lower()
    ]
    errors = [f for f in disc_findings if not f.passed and f.severity == "error"]
    assert len(errors) == 0
