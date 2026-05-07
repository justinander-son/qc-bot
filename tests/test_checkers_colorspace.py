# tests/test_checkers_colorspace.py
import shutil
import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def test_image_skipped(mock_config, valid_png):
    from checkers.colorspace import ColorspaceChecker
    findings = ColorspaceChecker(mock_config).run(valid_png)
    # PNG checker should return no error findings
    errors = [f for f in findings if not f.passed and f.severity == "error"]
    assert len(errors) == 0


def test_h264_yuv420p_no_errors(mock_config, valid_mp4):
    from checkers.colorspace import ColorspaceChecker
    findings = ColorspaceChecker(mock_config).run(valid_mp4)
    errors = [f for f in findings if not f.passed and f.severity == "error"]
    assert len(errors) == 0


def test_finding_contains_pix_fmt(mock_config, valid_mp4):
    from checkers.colorspace import ColorspaceChecker
    findings = ColorspaceChecker(mock_config).run(valid_mp4)
    detail_values = [str(v) for f in findings for v in f.details.values()]
    assert any("yuv420p" in v for v in detail_values)
