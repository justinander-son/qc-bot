import shutil
import subprocess
import pytest
from pathlib import Path

_FFMPEG = shutil.which("ffmpeg")
_NO_FFMPEG = pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg not installed")


def _ffmpeg(args):
    if _FFMPEG is None:
        pytest.skip("ffmpeg not installed")
    result = subprocess.run([_FFMPEG] + args, capture_output=True)
    if result.returncode != 0:
        pytest.skip(f"ffmpeg fixture generation failed: {result.stderr.decode()[:200]}")


@pytest.fixture
def mock_config(tmp_path):
    from core.config import ProjectConfig, QCParams
    (tmp_path / "source").mkdir()
    (tmp_path / "approved").mkdir()
    return ProjectConfig(
        project_name="test",
        source_dir=tmp_path / "source",
        approved_dir=tmp_path / "approved",
        db_path=tmp_path / "test.db",
        pipeline_version="2.0.0",
        filename_regex=r"^(\d{3})_([A-Za-z0-9]+)_(T|All Walls|Brick|Floor|WallA|WallB|WallC|WallD)_(FullRes|HalfRes|QRes)_(v\d{6}[a-z]?)(?:_(\d+))?\.(mp4|jpg|png)$",
        allowed_resolutions=["2318x1632", "4636x3264", "13584x1712"],
        allowed_codecs=["h264", "prores", "mjpeg", "png"],
        target_fps="30/1",
        num_workers=1,
        airtable=None,
        qc=QCParams(
            content_fade_margin=0.5,
            black_sensitivity_duration=0.03,
            black_pixel_threshold=0.10,
            black_picture_threshold=0.98,
            freeze_sensitivity_duration=0.03,
            freeze_noise_floor="-60dB",
            loudness_target_lufs=-23.0,
            loudness_tolerance_lu=1.0,
        ),
    )


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture(scope="session")
def valid_mp4(tmp_path_factory):
    # 2318x1632, 30fps, h264, yuv420p, 2s, with sine audio
    p = tmp_path_factory.mktemp("media") / "valid.mp4"
    _ffmpeg([
        "-f", "lavfi", "-i", "testsrc=size=2318x1632:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(p),
    ])
    return p


@pytest.fixture(scope="session")
def silent_mp4(tmp_path_factory):
    # 2318x1632, 30fps, no audio
    p = tmp_path_factory.mktemp("media") / "silent.mp4"
    _ffmpeg([
        "-f", "lavfi", "-i", "testsrc=size=2318x1632:rate=30",
        "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(p),
    ])
    return p


@pytest.fixture(scope="session")
def black_mp4(tmp_path_factory):
    # 4s clip: 1s white → 2s black → 1s white so black falls outside both fade margins
    p = tmp_path_factory.mktemp("media") / "black.mp4"
    _ffmpeg([
        "-f", "lavfi",
        "-i", "color=c=white:size=320x240:rate=30",
        "-f", "lavfi",
        "-i", "color=c=black:size=320x240:rate=30",
        "-f", "lavfi",
        "-i", "color=c=white:size=320x240:rate=30",
        "-filter_complex",
        "[0]trim=0:1[a];[1]trim=0:2[b];[2]trim=0:1[c];[a][b][c]concat=n=3:v=1:a=0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(p),
    ])
    return p


@pytest.fixture(scope="session")
def frozen_mp4(tmp_path_factory):
    # 3s constant-colour (blue) — may trigger freezedetect
    p = tmp_path_factory.mktemp("media") / "frozen.mp4"
    _ffmpeg([
        "-f", "lavfi", "-i", "color=blue:size=2318x1632:rate=30",
        "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(p),
    ])
    return p


@pytest.fixture(scope="session")
def valid_png(tmp_path_factory):
    p = tmp_path_factory.mktemp("media") / "valid.png"
    _ffmpeg([
        "-f", "lavfi", "-i", "color=red:size=2318x1632",
        "-frames:v", "1", str(p),
    ])
    return p


@pytest.fixture(scope="session")
def wrong_res_mp4(tmp_path_factory):
    p = tmp_path_factory.mktemp("media") / "wrong_res.mp4"
    _ffmpeg([
        "-f", "lavfi", "-i", "testsrc=size=640x480:rate=30",
        "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(p),
    ])
    return p


@pytest.fixture(scope="session")
def wrong_fps_mp4(tmp_path_factory):
    p = tmp_path_factory.mktemp("media") / "wrong_fps.mp4"
    _ffmpeg([
        "-f", "lavfi", "-i", "testsrc=size=2318x1632:rate=24",
        "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(p),
    ])
    return p


@pytest.fixture(scope="session")
def empty_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("media") / "empty.mp4"
    p.touch()
    return p


@pytest.fixture
def named_copy(tmp_path):
    def _copy(src: Path, name: str) -> Path:
        dest = tmp_path / name
        shutil.copy2(src, dest)
        return dest
    return _copy
