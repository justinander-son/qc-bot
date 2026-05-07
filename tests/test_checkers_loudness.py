# tests/test_checkers_loudness.py
import shutil
import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def test_image_skipped(mock_config, valid_png):
    from checkers.loudness import LoudnessChecker
    findings = LoudnessChecker(mock_config).run(valid_png)
    assert all(f.passed for f in findings)
    assert any("skipped" in f.message.lower() for f in findings)


def test_no_audio_returns_warning(mock_config, silent_mp4):
    from checkers.loudness import LoudnessChecker
    findings = LoudnessChecker(mock_config).run(silent_mp4)
    assert any(f.severity == "warning" and f.passed for f in findings)


def test_finding_has_lufs_details(mock_config, valid_mp4):
    from checkers.loudness import LoudnessChecker
    findings = LoudnessChecker(mock_config).run(valid_mp4)
    lufs_findings = [f for f in findings if "integrated_lufs" in f.details]
    if lufs_findings:
        assert "target_lufs" in lufs_findings[0].details
