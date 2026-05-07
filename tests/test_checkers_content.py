# tests/test_checkers_content.py
import shutil
import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def test_clean_video_passes(mock_config, valid_mp4):
    from checkers.content import ContentChecker
    findings = ContentChecker(mock_config).run(valid_mp4)
    errors = [f for f in findings if not f.passed and f.severity == "error"]
    assert len(errors) == 0


def test_black_video_fails(mock_config, black_mp4):
    from checkers.content import ContentChecker
    # clip is 4s (1s white → 2s black → 1s white); pass actual duration so fade margins are correct
    findings = ContentChecker(mock_config)._run_with_duration(black_mp4, total_duration=4.0)
    errors = [f for f in findings if not f.passed and f.severity == "error"]
    assert len(errors) > 0
    assert any("black" in f.message.lower() for f in errors)


@pytest.mark.xfail(strict=False, reason="freezedetect on constant-colour synthetic clips varies by ffmpeg build")
def test_frozen_video_fails(mock_config, frozen_mp4):
    from checkers.content import ContentChecker
    findings = ContentChecker(mock_config)._run_with_duration(frozen_mp4, total_duration=3.0)
    errors = [f for f in findings if not f.passed and f.severity == "error"]
    assert any("frozen" in f.message.lower() for f in errors)


def test_image_skipped(mock_config, valid_png):
    from checkers.content import ContentChecker
    findings = ContentChecker(mock_config).run(valid_png)
    assert all(f.passed for f in findings)
