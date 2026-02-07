"""
Tests for transcoder.py - TranscodeWorker unit tests.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from models import TranscodeJob


# ─── check_nvenc_support ─────────────────────────────────────────────────────


class TestCheckNvencSupport:
    """Tests for check_nvenc_support function."""

    def test_both_available(self):
        """Should detect HandBrake and FFmpeg NVENC."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            result.stdout = "nvenc hevc_nvenc h264_nvenc"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run):
            from transcoder import check_nvenc_support
            support = check_nvenc_support()
            assert support["handbrake_nvenc"] is True
            assert support["ffmpeg_nvenc_h265"] is True
            assert support["ffmpeg_nvenc_h264"] is True

    def test_nothing_available(self):
        """Should handle no NVENC support."""
        def mock_run(cmd, **kwargs):
            raise FileNotFoundError("not found")

        with patch("transcoder.subprocess.run", side_effect=mock_run):
            from transcoder import check_nvenc_support
            support = check_nvenc_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is False
            assert support["ffmpeg_nvenc_h264"] is False

    def test_ffmpeg_only(self):
        """Should detect FFmpeg NVENC when HandBrake missing."""
        def mock_run(cmd, **kwargs):
            result = MagicMock()
            if cmd[0] == "HandBrakeCLI":
                raise FileNotFoundError()
            result.stdout = "hevc_nvenc h264_nvenc"
            result.stderr = ""
            return result

        with patch("transcoder.subprocess.run", side_effect=mock_run):
            from transcoder import check_nvenc_support
            support = check_nvenc_support()
            assert support["handbrake_nvenc"] is False
            assert support["ffmpeg_nvenc_h265"] is True
            assert support["ffmpeg_nvenc_h264"] is True

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

        with patch("transcoder.subprocess.run", side_effect=mock_run):
            from transcoder import check_nvenc_support
            support = check_nvenc_support()
            assert support["handbrake_nvenc"] is True


# ─── TranscodeWorker._discover_source_files ──────────────────────────────────


class TestDiscoverSourceFiles:
    """Tests for _discover_source_files method."""

    def _make_worker(self):
        """Create a TranscodeWorker with mocked dependencies."""
        with patch("transcoder.check_nvenc_support", return_value={
            "handbrake_nvenc": True,
            "ffmpeg_nvenc_h265": True,
            "ffmpeg_nvenc_h264": True,
        }):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_finds_mkv_files(self, sample_mkv_dir):
        """Should find all MKV files in directory."""
        worker = self._make_worker()
        files = worker._discover_source_files(str(sample_mkv_dir["dir"]))
        assert len(files) == 2
        names = {f.name for f in files}
        assert "title_main.mkv" in names
        assert "title_extra.mkv" in names

    def test_sorted_by_size(self, sample_mkv_dir):
        """Files should be sorted largest first."""
        worker = self._make_worker()
        files = worker._discover_source_files(str(sample_mkv_dir["dir"]))
        assert files[0].name == "title_main.mkv"  # 10KB > 2KB

    def test_single_file(self, tmp_path):
        """Should handle single MKV file."""
        mkv = tmp_path / "movie.mkv"
        mkv.write_bytes(b"\x00" * 100)
        worker = self._make_worker()
        files = worker._discover_source_files(str(mkv))
        assert len(files) == 1
        assert files[0].name == "movie.mkv"

    def test_no_mkv_files(self, tmp_path):
        """Should return empty list when no MKV files found."""
        (tmp_path / "readme.txt").write_text("not a video")
        worker = self._make_worker()
        files = worker._discover_source_files(str(tmp_path))
        assert len(files) == 0

    def test_non_mkv_single_file(self, tmp_path):
        """Should return empty list for non-MKV single file."""
        txt = tmp_path / "readme.txt"
        txt.write_text("not a video")
        worker = self._make_worker()
        files = worker._discover_source_files(str(txt))
        assert len(files) == 0

    def test_ignores_non_mkv_in_dir(self, tmp_path):
        """Should only return MKV files from directory."""
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
        with patch("transcoder.check_nvenc_support", return_value={
            "handbrake_nvenc": True,
            "ffmpeg_nvenc_h265": True,
            "ffmpeg_nvenc_h264": True,
        }):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_normal_title(self):
        """Normal title should produce clean output path."""
        worker = self._make_worker()
        result = worker._determine_output_path("The Matrix", "/data/raw/matrix")
        assert "The Matrix" in str(result)
        assert str(result).startswith(str(Path(settings.completed_path)))

    def test_title_with_special_chars(self):
        """Special characters in title should be removed."""
        worker = self._make_worker()
        result = worker._determine_output_path('Movie: "Title"', "/data/raw/movie")
        path_str = str(result)
        assert ":" not in Path(path_str).name
        assert '"' not in Path(path_str).name

    def test_uses_movies_subdir(self):
        """Output should go into movies subdirectory."""
        worker = self._make_worker()
        result = worker._determine_output_path("Test", "/data/raw/test")
        assert settings.movies_subdir in str(result)


# ─── TranscodeWorker._cleanup_source ─────────────────────────────────────────


class TestCleanupSource:
    """Tests for _cleanup_source method."""

    def _make_worker(self):
        with patch("transcoder.check_nvenc_support", return_value={
            "handbrake_nvenc": True,
            "ffmpeg_nvenc_h265": True,
            "ffmpeg_nvenc_h264": True,
        }):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_cleanup_directory(self, tmp_path):
        """Should remove entire directory."""
        target = tmp_path / "movie_dir"
        target.mkdir()
        (target / "file.mkv").write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        worker._cleanup_source(str(target))
        assert not target.exists()

    def test_cleanup_single_file(self, tmp_path):
        """Should remove single file."""
        target = tmp_path / "movie.mkv"
        target.write_bytes(b"\x00" * 100)

        worker = self._make_worker()
        worker._cleanup_source(str(target))
        assert not target.exists()

    def test_cleanup_nonexistent(self, tmp_path):
        """Should handle non-existent paths gracefully."""
        worker = self._make_worker()
        # Should not raise for directory check
        path = str(tmp_path / "nonexistent")
        # Path doesn't exist, so is_file() and is_dir() both return False
        worker._cleanup_source(path)  # Should not raise


# ─── TranscodeWorker properties ──────────────────────────────────────────────


class TestWorkerProperties:
    """Tests for TranscodeWorker properties."""

    def _make_worker(self):
        with patch("transcoder.check_nvenc_support", return_value={
            "handbrake_nvenc": True,
            "ffmpeg_nvenc_h265": True,
            "ffmpeg_nvenc_h264": True,
        }):
            from transcoder import TranscodeWorker
            return TranscodeWorker()

    def test_initial_state(self):
        """Worker should start not running."""
        worker = self._make_worker()
        assert worker.is_running is False
        assert worker.queue_size == 0
        assert worker.current_job is None

    def test_shutdown_sets_event(self):
        """shutdown() should set the shutdown event."""
        worker = self._make_worker()
        assert not worker._shutdown_event.is_set()
        worker.shutdown()
        assert worker._shutdown_event.is_set()


# Import settings for use in output path tests
from config import settings
