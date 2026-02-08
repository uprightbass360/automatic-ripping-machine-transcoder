"""
Tests for transcoder.py - TranscodeWorker unit tests.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from models import TranscodeJob


# Default GPU support dict for mocking
def _gpu_support_all():
    return {
        "handbrake_nvenc": True,
        "ffmpeg_nvenc_h265": True,
        "ffmpeg_nvenc_h264": True,
        "ffmpeg_vaapi_h265": True,
        "ffmpeg_vaapi_h264": True,
        "ffmpeg_amf_h265": True,
        "ffmpeg_amf_h264": True,
        "ffmpeg_qsv_h265": True,
        "ffmpeg_qsv_h264": True,
        "vaapi_device": True,
    }


def _gpu_support_none():
    return {k: False for k in _gpu_support_all()}


# ─── check_gpu_support ──────────────────────────────────────────────────────


class TestCheckGpuSupport:
    """Tests for check_gpu_support function."""

    def test_all_available(self):
        """Should detect all GPU encoders."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.stdout = "nvenc hevc_nvenc h264_nvenc hevc_vaapi h264_vaapi hevc_amf h264_amf hevc_qsv h264_qsv"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=True):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is True
            assert support["ffmpeg_nvenc_h265"] is True
            assert support["ffmpeg_nvenc_h264"] is True
            assert support["ffmpeg_vaapi_h265"] is True
            assert support["ffmpeg_vaapi_h264"] is True
            assert support["ffmpeg_amf_h265"] is True
            assert support["ffmpeg_amf_h264"] is True
            assert support["ffmpeg_qsv_h265"] is True
            assert support["ffmpeg_qsv_h264"] is True
            assert support["vaapi_device"] is True

    def test_nothing_available(self):
        """Should handle no GPU support."""
        def mock_run(cmd, **kwargs):
            raise FileNotFoundError("not found")

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is False
            assert support["ffmpeg_nvenc_h264"] is False
            assert support["ffmpeg_vaapi_h265"] is False
            assert support["ffmpeg_vaapi_h264"] is False
            assert support["ffmpeg_amf_h265"] is False
            assert support["ffmpeg_amf_h264"] is False
            assert support["ffmpeg_qsv_h265"] is False
            assert support["ffmpeg_qsv_h264"] is False
            assert support["vaapi_device"] is False

    def test_ffmpeg_only_nvenc(self):
        """Should detect FFmpeg NVENC when HandBrake missing."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_nvenc h264_nvenc"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is True
            assert support["ffmpeg_nvenc_h264"] is True
            assert support["ffmpeg_vaapi_h265"] is False
            assert support["ffmpeg_vaapi_h264"] is False

    def test_vaapi_only(self):
        """Should detect VAAPI encoders for AMD GPU."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_vaapi h264_vaapi"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=True):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is False
            assert support["ffmpeg_vaapi_h265"] is True
            assert support["ffmpeg_vaapi_h264"] is True
            assert support["vaapi_device"] is True

    def test_qsv_only(self):
        """Should detect QSV encoders for Intel GPU."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_qsv h264_qsv"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=True):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is False
            assert support["ffmpeg_qsv_h265"] is True
            assert support["ffmpeg_qsv_h264"] is True
            assert support["vaapi_device"] is True

    def test_handbrake_nvenc_in_stderr(self):
        """HandBrake may report NVENC in stderr."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                result.stdout = ""
                result.stderr = "NVENC encoder available"
            else:
                result.stdout = ""
                result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["handbrake_nvenc"] is True

    def test_vaapi_device_not_found(self):
        """Should report no VAAPI device when /dev/dri/renderD128 missing."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_vaapi h264_vaapi"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run), \
             patch("transcoder.os.path.exists", return_value=False):
            from transcoder import check_gpu_support
            support = check_gpu_support()
            assert support["ffmpeg_vaapi_h265"] is True
            assert support["vaapi_device"] is False

    def test_backward_compat_alias(self):
        """check_nvenc_support should be an alias for check_gpu_support."""
        from transcoder import check_nvenc_support, check_gpu_support
        assert check_nvenc_support is check_gpu_support


# ─── Encoder family detection ────────────────────────────────────────────────


class TestEncoderFamilyDetection:
    """Tests for _detect_encoder_family and _select_backend."""

    def _make_worker(self, gpu_support=None, video_encoder="nvenc_h265"):
        if gpu_support is None:
            gpu_support = _gpu_support_all()
        with patch("transcoder.check_gpu_support", return_value=gpu_support), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.video_encoder = video_encoder
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_nvenc_family(self):
        worker = self._make_worker(video_encoder="nvenc_h265")
        assert worker._encoder_family == "nvenc"

    def test_vaapi_family(self):
        worker = self._make_worker(video_encoder="vaapi_h265")
        assert worker._encoder_family == "vaapi"

    def test_amf_family(self):
        worker = self._make_worker(video_encoder="amf_h265")
        assert worker._encoder_family == "amf"

    def test_qsv_family(self):
        worker = self._make_worker(video_encoder="qsv_h265")
        assert worker._encoder_family == "qsv"

    def test_software_family(self):
        worker = self._make_worker(video_encoder="x265")
        assert worker._encoder_family == "software"

    def test_nvenc_uses_handbrake_when_available(self):
        worker = self._make_worker(video_encoder="nvenc_h265")
        assert worker._encoder_backend == "handbrake"

    def test_nvenc_falls_back_to_ffmpeg(self):
        support = _gpu_support_none()
        support["ffmpeg_nvenc_h265"] = True
        worker = self._make_worker(gpu_support=support, video_encoder="nvenc_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_vaapi_always_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="vaapi_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_amf_always_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="amf_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_qsv_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="qsv_h265")
        assert worker._encoder_backend == "ffmpeg"

    def test_software_uses_ffmpeg(self):
        worker = self._make_worker(video_encoder="x264")
        assert worker._encoder_backend == "ffmpeg"


# ─── FFmpeg command building ─────────────────────────────────────────────────


class TestBuildFfmpegCommand:
    """Tests for _build_ffmpeg_command with different encoder families."""

    def _make_worker(self, video_encoder="nvenc_h265"):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()), \
             patch("transcoder.settings") as mock_settings:
            mock_settings.video_encoder = video_encoder
            mock_settings.video_quality = 22
            mock_settings.audio_encoder = "copy"
            mock_settings.subtitle_mode = "all"
            from transcoder import TranscodeWorker
            worker = TranscodeWorker()
            # Re-patch settings for command building
            with patch("transcoder.settings", mock_settings):
                return worker, mock_settings

    def test_nvenc_h265_command(self):
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel" in cmd
        assert "cuda" in cmd
        assert "hevc_nvenc" in cmd
        assert "-cq" in cmd

    def test_nvenc_h264_command(self):
        worker, settings = self._make_worker("nvenc_h264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "h264_nvenc" in cmd

    def test_vaapi_h265_command(self):
        worker, settings = self._make_worker("vaapi_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel" in cmd
        assert "vaapi" in cmd
        assert "hevc_vaapi" in cmd
        assert "-rc_mode" in cmd
        assert "CQP" in cmd
        assert "-qp" in cmd

    def test_vaapi_h264_command(self):
        worker, settings = self._make_worker("vaapi_h264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "h264_vaapi" in cmd

    def test_amf_h265_command(self):
        worker, settings = self._make_worker("amf_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "hevc_amf" in cmd
        assert "-rc" in cmd
        assert "cqp" in cmd
        assert "-qp_i" in cmd

    def test_qsv_h265_command(self):
        worker, settings = self._make_worker("qsv_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel" in cmd
        assert "qsv" in cmd
        assert "hevc_qsv" in cmd
        assert "-global_quality" in cmd

    def test_qsv_h264_command(self):
        worker, settings = self._make_worker("qsv_h264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "h264_qsv" in cmd
        assert "-global_quality" in cmd

    def test_software_x265_command(self):
        worker, settings = self._make_worker("x265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "libx265" in cmd
        assert "-crf" in cmd
        assert "-hwaccel" not in cmd

    def test_software_x264_command(self):
        worker, settings = self._make_worker("x264")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "libx264" in cmd
        assert "-crf" in cmd
        assert "-hwaccel" not in cmd

    def test_audio_copy(self):
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        idx = cmd.index("-c:a")
        assert cmd[idx + 1] == "copy"

    def test_subtitle_all(self):
        worker, settings = self._make_worker("nvenc_h265")
        with patch("transcoder.settings", settings):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        idx = cmd.index("-c:s")
        assert cmd[idx + 1] == "copy"

    def test_vaapi_includes_device_path(self):
        worker, settings = self._make_worker("vaapi_h265")
        with patch("transcoder.settings", settings), \
             patch.dict("os.environ", {"VAAPI_DEVICE": "/dev/dri/renderD128"}):
            cmd = worker._build_ffmpeg_command(Path("/in.mkv"), Path("/out.mkv"))
        assert "-hwaccel_device" in cmd
        device_idx = cmd.index("-hwaccel_device")
        assert cmd[device_idx + 1] == "/dev/dri/renderD128"


# ─── TranscodeWorker._discover_source_files ──────────────────────────────────


class TestDiscoverSourceFiles:
    """Tests for _discover_source_files method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_finds_mkv_files(self, sample_mkv_dir):
        worker = self._make_worker()
        files = worker._discover_source_files(str(sample_mkv_dir["dir"]))
        assert len(files) == 2
        names = {f.name for f in files}
        assert "title_main.mkv" in names
        assert "title_extra.mkv" in names

    def test_sorted_by_size(self, sample_mkv_dir):
        worker = self._make_worker()
        files = worker._discover_source_files(str(sample_mkv_dir["dir"]))
        assert files[0].name == "title_main.mkv"

    def test_single_file(self, tmp_path):
        mkv = tmp_path / "movie.mkv"
        mkv.write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        files = worker._discover_source_files(str(mkv))
        assert len(files) == 1
        assert files[0].name == "movie.mkv"

    def test_no_mkv_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a video")
        worker = self._make_worker()
        files = worker._discover_source_files(str(tmp_path))
        assert len(files) == 0

    def test_non_mkv_single_file(self, tmp_path):
        txt = tmp_path / "readme.txt"
        txt.write_text("not a video")
        worker = self._make_worker()
        files = worker._discover_source_files(str(txt))
        assert len(files) == 0

    def test_ignores_non_mkv_in_dir(self, tmp_path):
        (tmp_path / "movie.mkv").write_bytes(b"\x00" * 100)
        (tmp_path / "cover.jpg").write_bytes(b"\x00" * 50)
        (tmp_path / "subs.srt").write_text("subtitle")
        worker = self._make_worker()
        files = worker._discover_source_files(str(tmp_path))
        assert len(files) == 1
        assert files[0].suffix == ".mkv"


# ─── TranscodeWorker._determine_output_path ──────────────────────────────────


class TestDetermineOutputPath:
    """Tests for _determine_output_path method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_normal_title(self):
        worker = self._make_worker()
        result = worker._determine_output_path("The Matrix", "/data/raw/matrix")
        assert "The Matrix" in str(result)
        assert str(result).startswith(str(Path(settings.completed_path)))

    def test_title_with_special_chars(self):
        worker = self._make_worker()
        result = worker._determine_output_path('Movie: "Title"', "/data/raw/movie")
        path_str = str(result)
        assert ":" not in Path(path_str).name
        assert '"' not in Path(path_str).name

    def test_uses_movies_subdir(self):
        worker = self._make_worker()
        result = worker._determine_output_path("Test", "/data/raw/test")
        assert settings.movies_subdir in str(result)


# ─── TranscodeWorker._cleanup_source ─────────────────────────────────────────


class TestCleanupSource:
    """Tests for _cleanup_source method."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_cleanup_directory(self, tmp_path):
        target = tmp_path / "movie_dir"
        target.mkdir()
        (target / "file.mkv").write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        worker._cleanup_source(str(target))
        assert not target.exists()

    def test_cleanup_single_file(self, tmp_path):
        target = tmp_path / "movie.mkv"
        target.write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        worker._cleanup_source(str(target))
        assert not target.exists()

    def test_cleanup_nonexistent(self, tmp_path):
        worker = self._make_worker()
        path = str(tmp_path / "nonexistent")
        worker._cleanup_source(path)  # Should not raise


# ─── TranscodeWorker properties ──────────────────────────────────────────────


class TestWorkerProperties:
    """Tests for TranscodeWorker properties."""

    def _make_worker(self):
        with patch("transcoder.check_gpu_support", return_value=_gpu_support_all()):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_initial_state(self):
        worker = self._make_worker()
        assert worker.is_running is False
        assert worker.queue_size == 0
        assert worker.current_job is None

    def test_shutdown_sets_event(self):
        worker = self._make_worker()
        assert not worker._shutdown_event.is_set()
        worker.shutdown()
        assert worker._shutdown_event.is_set()


# Import settings for use in output path tests
from config import settings
