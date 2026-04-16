"""
Deep coverage tests for transcoder.py — queue_job paths, process_job flow,
worker run loop, audio passthrough, multi-title routing.
"""

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from models import TranscodeJob, TranscodeJobDB, JobStatus, Base


def _gpu_support_none():
    return {
        "handbrake_nvenc": False, "ffmpeg_nvenc_h265": False, "ffmpeg_nvenc_h264": False,
        "ffmpeg_vaapi_h265": False, "ffmpeg_vaapi_h264": False,
        "ffmpeg_amf_h265": False, "ffmpeg_amf_h264": False,
        "ffmpeg_qsv_h265": False, "ffmpeg_qsv_h264": False,
        "vaapi_device": False, "handbrake_qsv": False,
    }


def _mock_scheme_software():
    """Build a mock software scheme for test fixtures."""
    from presets import Preset, Scheme, Encoder
    preset = Preset(
        slug="test_sw", name="Test Software", scheme="software",
        shared={"video_encoder": "x265", "audio_encoder": "copy", "subtitle_mode": "all"},
        tiers={
            "dvd": {"handbrake_preset": "H.265 MKV 720p30", "video_quality": 22},
            "bluray": {"handbrake_preset": "H.265 MKV 1080p30", "video_quality": 22},
            "uhd": {"handbrake_preset": "H.265 MKV 2160p60 4K", "video_quality": 22},
        },
    )
    return Scheme(
        slug="software", name="Software (CPU)",
        supported_encoders=[Encoder(slug="x265", name="Software x265")],
        supported_audio_encoders=["copy", "aac"],
        supported_subtitle_modes=["all", "first", "none"],
        built_in_presets=[preset],
    )


@pytest_asyncio.fixture
async def worker_with_db(tmp_path):
    """Create a TranscodeWorker with a real test DB."""
    from transcoder import TranscodeWorker

    db_path = str(tmp_path / "test_worker.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def test_get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    import database as db_module
    with patch.object(db_module, "get_db", test_get_db), \
         patch("transcoder.get_db", test_get_db), \
         patch("main.active_scheme", _mock_scheme_software()):
        worker = TranscodeWorker(gpu_support=_gpu_support_none())
        yield worker, session_factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── queue_job paths ──────────────────────────────────────────────────────────

class TestQueueJobPaths:
    @pytest.mark.asyncio
    async def test_queue_job_creates_new_job(self, worker_with_db):
        """Cover queue_job new job creation path."""
        worker, session_factory = worker_with_db
        job_id, created = await worker.queue_job(
            job_id=1, source_path="/test/movie", title="Test Movie"
        )
        assert created is True
        assert job_id == 1

    @pytest.mark.asyncio
    async def test_queue_job_dedup_returns_existing(self, worker_with_db):
        """Cover queue_job: duplicate detection by ID."""
        worker, session_factory = worker_with_db

        # Queue first job
        job_id1, created1 = await worker.queue_job(
            job_id=1, source_path="/test/movie", title="Movie"
        )
        assert created1 is True

        # Queue same ID — should dedup (active job)
        job_id2, created2 = await worker.queue_job(
            job_id=1, source_path="/test/movie", title="Movie Again"
        )
        assert created2 is False
        assert job_id2 == job_id1

    @pytest.mark.asyncio
    async def test_queue_job_requeue_failed(self, worker_with_db):
        """Cover queue_job: re-queue a failed job by same ID."""
        worker, session_factory = worker_with_db

        # Create a failed job in DB
        async with session_factory() as session:
            job_db = TranscodeJobDB(
                id=50, title="Failed Job", source_path="/test/fail",
                status=JobStatus.FAILED
            )
            session.add(job_db)
            await session.commit()

        job_id, created = await worker.queue_job(
            job_id=50, source_path="/test/fail", title="Failed Job"
        )
        assert created is True
        assert job_id == 50

    @pytest.mark.asyncio
    async def test_queue_job_with_overrides_and_tracks(self, worker_with_db):
        """Cover queue_job with config_overrides and tracks metadata."""
        worker, session_factory = worker_with_db

        overrides = {"video_encoder": "hevc_nvenc", "video_quality": 18}
        tracks = [{"track_number": "1", "title": "Episode 1"}]

        job_id, created = await worker.queue_job(
            job_id=3, source_path="/test/series", title="Series",
            config_overrides=overrides,
            multi_title=True, tracks=tracks,
            folder_name="Series/Season 1", title_name="S01E01",
        )
        assert created is True

        # Verify data persisted
        async with session_factory() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
            )
            job_db = result.scalar_one()
            assert job_db.config_overrides is not None
            assert job_db.multi_title == 1
            assert job_db.track_metadata is not None
            assert job_db.folder_name == "Series/Season 1"


# ── Worker run loop ──────────────────────────────────────────────────────────

class TestWorkerRunLoop:
    @pytest.mark.asyncio
    async def test_run_loop_timeout_continues(self, worker_with_db):
        """Cover run() lines 322-323: TimeoutError continues loop."""
        worker, _ = worker_with_db

        async def shutdown_after_loop():
            # Give the loop time to hit one timeout cycle
            await asyncio.sleep(6.0)
            worker.shutdown()

        with patch.object(worker, "_load_pending_jobs", new_callable=AsyncMock):
            shutdown_task = asyncio.create_task(shutdown_after_loop())
            await asyncio.wait_for(worker.run(), timeout=15.0)
            shutdown_task.cancel()

        assert not worker.is_running

    @pytest.mark.asyncio
    async def test_run_loop_handles_process_error(self, worker_with_db):
        """Cover run() lines 330-332: exception in process_job."""
        worker, _ = worker_with_db

        job = TranscodeJob(id=999, title="Crash Job", source_path="/fake")

        async def shutdown_after_error():
            await asyncio.sleep(0.5)
            worker.shutdown()

        with patch.object(worker, "_load_pending_jobs", new_callable=AsyncMock), \
             patch.object(worker, "_process_job", side_effect=RuntimeError("boom")), \
             patch("transcoder.asyncio.sleep", new_callable=AsyncMock):
            await worker._queue.put(job)
            shutdown_task = asyncio.create_task(shutdown_after_error())
            await asyncio.wait_for(worker.run(), timeout=10.0)
            shutdown_task.cancel()


# ── _load_job_metadata ───────────────────────────────────────────────────────

class TestLoadJobMetadata:
    @pytest.mark.asyncio
    async def test_load_metadata_with_overrides(self, worker_with_db):
        """Cover _load_job_metadata lines 406-413: config_overrides and folder_name."""
        worker, session_factory = worker_with_db

        overrides = {"video_encoder": "hevc_nvenc"}
        async with session_factory() as session:
            job_db = TranscodeJobDB(
                id=60, title="Test", source_path="/test",
                status=JobStatus.PENDING,
                config_overrides=json.dumps(overrides),
                folder_name="Movies/Test (2024)",
                title_name="Test (2024)",
                video_type="movie", year="2024",
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        result = await worker._load_job_metadata(job_id)
        loaded_overrides, video_type, year, folder_name, title_name = result
        assert loaded_overrides == overrides
        assert video_type == "movie"
        assert year == "2024"
        assert folder_name == "Movies/Test (2024)"
        assert title_name == "Test (2024)"

    @pytest.mark.asyncio
    async def test_load_metadata_invalid_json(self, worker_with_db):
        """Cover _load_job_metadata line 408: invalid JSON in overrides."""
        worker, session_factory = worker_with_db

        async with session_factory() as session:
            job_db = TranscodeJobDB(
                id=61, title="Test", source_path="/test",
                status=JobStatus.PENDING,
                config_overrides="not valid json{{{",
            )
            session.add(job_db)
            await session.commit()
            await session.refresh(job_db)
            job_id = job_db.id

        result = await worker._load_job_metadata(job_id)
        overrides, _, _, _, _ = result
        assert overrides is None  # Invalid JSON falls back to None


# ── _setup_job_logging ───────────────────────────────────────────────────────

class TestSetupJobLogging:
    def test_setup_job_logging_exception(self, worker_with_db):
        """Cover _setup_job_logging lines 380-382: exception returns None."""
        worker, _ = worker_with_db

        with patch("transcoder.settings") as mock_settings:
            mock_settings.log_path = "/nonexistent/impossible/path"
            result = worker._setup_job_logging(999, "test.log")
            assert result is None


# ── _resolve_and_stabilize ───────────────────────────────────────────────────

class TestResolveAndStabilize:
    @pytest.mark.asyncio
    async def test_resolve_changes_path(self, worker_with_db):
        """Cover _resolve_and_stabilize lines 480-481: path changes."""
        worker, _ = worker_with_db

        job = TranscodeJob(id=1, title="Test", source_path="/old/path")

        with patch.object(worker, "_resolve_source_path", return_value="/new/path"), \
             patch.object(worker, "_update_job", new_callable=AsyncMock), \
             patch.object(worker, "_wait_for_stable", new_callable=AsyncMock):
            await worker._resolve_and_stabilize(job)
            assert job.source_path == "/new/path"

    @pytest.mark.asyncio
    async def test_resolve_no_change(self, worker_with_db):
        """Cover _resolve_and_stabilize: path stays the same."""
        worker, _ = worker_with_db

        job = TranscodeJob(id=1, title="Test", source_path="/same/path")

        with patch.object(worker, "_resolve_source_path", return_value="/same/path"), \
             patch.object(worker, "_update_job", new_callable=AsyncMock) as mock_update, \
             patch.object(worker, "_wait_for_stable", new_callable=AsyncMock):
            await worker._resolve_and_stabilize(job)
            mock_update.assert_not_called()


# ── _discover_or_passthrough ─────────────────────────────────────────────────

class TestDiscoverOrPassthrough:
    @pytest.mark.asyncio
    async def test_discover_empty_then_reresolve(self, worker_with_db):
        """Cover _discover_or_passthrough lines 491-494: empty then re-resolve."""
        worker, _ = worker_with_db

        job = TranscodeJob(id=1, title="Test", source_path="/test/path")
        fake_files = [Path("/test/path/movie.mkv")]

        call_count = 0
        def discover_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []  # First call: empty
            return fake_files  # After re-resolve: found files

        with patch.object(worker, "_discover_source_files", side_effect=discover_side_effect), \
             patch.object(worker, "_resolve_source_path", return_value="/new/path"), \
             patch.object(worker, "_update_job", new_callable=AsyncMock), \
             patch.object(worker, "_wait_for_stable", new_callable=AsyncMock):
            result = await worker._discover_or_passthrough(job)
            assert result == fake_files

    @pytest.mark.asyncio
    async def test_discover_audio_passthrough(self, worker_with_db):
        """Cover _discover_or_passthrough: audio files trigger passthrough."""
        worker, _ = worker_with_db

        job = TranscodeJob(id=1, title="Audio CD", source_path="/test/audio")

        with patch.object(worker, "_discover_source_files", return_value=[]), \
             patch.object(worker, "_resolve_source_path", return_value="/test/audio"), \
             patch.object(worker, "_discover_audio_files", return_value=[Path("/test/audio/track01.flac")]), \
             patch.object(worker, "_passthrough_audio", new_callable=AsyncMock) as mock_passthrough:
            result = await worker._discover_or_passthrough(job)
            assert result == []
            mock_passthrough.assert_called_once()

    @pytest.mark.asyncio
    async def test_discover_no_files_raises(self, worker_with_db):
        """Cover _discover_or_passthrough: no video or audio raises."""
        worker, _ = worker_with_db

        job = TranscodeJob(id=1, title="Empty", source_path="/test/empty")

        with patch.object(worker, "_discover_source_files", return_value=[]), \
             patch.object(worker, "_resolve_source_path", return_value="/test/empty"), \
             patch.object(worker, "_discover_audio_files", return_value=[]):
            with pytest.raises(ValueError, match="No video or audio"):
                await worker._discover_or_passthrough(job)


# ── _transcode_file_ffmpeg ───────────────────────────────────────────────────

class _AsyncLineIterator:
    """Helper to mock async stdout line iteration."""
    def __init__(self, lines):
        self._lines = iter(lines)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._lines)
        except StopIteration:
            raise StopAsyncIteration


class TestTranscodeFileFFmpeg:
    @pytest.mark.asyncio
    async def test_ffmpeg_transcode_success(self, worker_with_db, tmp_path):
        """Cover _transcode_file_ffmpeg lines 1258-1292: successful transcode."""
        worker, _ = worker_with_db

        source = tmp_path / "input.mkv"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "output.mkv"

        mock_proc = AsyncMock()
        mock_proc.stdout = _AsyncLineIterator([
            b"frame=100 fps=30 time=00:01:00.00 bitrate=5000kbits/s\n",
            b"frame=200 fps=30 time=00:02:00.00 bitrate=5000kbits/s\n",
        ])
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(worker, "_get_video_resolution", new_callable=AsyncMock, return_value=(1920, 1080)), \
             patch.object(worker, "_get_video_duration", new_callable=AsyncMock, return_value=3600.0), \
             patch.object(worker, "_build_ffmpeg_command", return_value=["ffmpeg", "-i", str(source), str(output)]), \
             patch.object(worker, "_update_progress", new_callable=AsyncMock):
            output.write_bytes(b"\x00" * 50)
            await worker._transcode_file_ffmpeg(source, output, job_id=1)

    @pytest.mark.asyncio
    async def test_ffmpeg_transcode_failure(self, worker_with_db, tmp_path):
        """Cover _transcode_file_ffmpeg: non-zero exit code."""
        worker, _ = worker_with_db

        source = tmp_path / "input.mkv"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "output.mkv"

        mock_proc = AsyncMock()
        mock_proc.stdout = _AsyncLineIterator([])
        mock_proc.wait = AsyncMock(return_value=1)
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(worker, "_get_video_resolution", new_callable=AsyncMock, return_value=(1920, 1080)), \
             patch.object(worker, "_get_video_duration", new_callable=AsyncMock, return_value=3600.0), \
             patch.object(worker, "_build_ffmpeg_command", return_value=["ffmpeg"]):
            with pytest.raises(RuntimeError, match="FFmpeg failed"):
                await worker._transcode_file_ffmpeg(source, output, job_id=1)

    @pytest.mark.asyncio
    async def test_ffmpeg_no_output_file(self, worker_with_db, tmp_path):
        """Cover _transcode_file_ffmpeg: output not created."""
        worker, _ = worker_with_db

        source = tmp_path / "input.mkv"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "output.mkv"

        mock_proc = AsyncMock()
        mock_proc.stdout = _AsyncLineIterator([])
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(worker, "_get_video_resolution", new_callable=AsyncMock, return_value=(1920, 1080)), \
             patch.object(worker, "_get_video_duration", new_callable=AsyncMock, return_value=3600.0), \
             patch.object(worker, "_build_ffmpeg_command", return_value=["ffmpeg"]):
            with pytest.raises(RuntimeError, match="Output file was not created"):
                await worker._transcode_file_ffmpeg(source, output, job_id=1)

    @pytest.mark.asyncio
    async def test_ffmpeg_no_duration(self, worker_with_db, tmp_path):
        """Cover _transcode_file_ffmpeg: no duration skips progress parsing."""
        worker, _ = worker_with_db

        source = tmp_path / "input.mkv"
        source.write_bytes(b"\x00" * 100)
        output = tmp_path / "output.mkv"

        mock_proc = AsyncMock()
        mock_proc.stdout = _AsyncLineIterator([
            b"frame=100 fps=30 time=00:01:00.00\n",
        ])
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(worker, "_get_video_resolution", new_callable=AsyncMock, return_value=(1920, 1080)), \
             patch.object(worker, "_get_video_duration", new_callable=AsyncMock, return_value=None), \
             patch.object(worker, "_build_ffmpeg_command", return_value=["ffmpeg"]), \
             patch.object(worker, "_update_progress", new_callable=AsyncMock) as mock_progress:
            output.write_bytes(b"\x00" * 50)
            await worker._transcode_file_ffmpeg(source, output, job_id=1)
            # Progress should NOT be updated since duration is None
            mock_progress.assert_not_called()


# ── _effective helper ────────────────────────────────────────────────────────

class TestEffectiveHelper:
    def test_effective_returns_override(self, worker_with_db):
        """Cover _effective line 133: override takes precedence."""
        worker, _ = worker_with_db
        result = worker._effective("delete_source", {"delete_source": False})
        assert result is False

    def test_effective_returns_global(self, worker_with_db):
        """Cover _effective line 134: falls back to settings."""
        worker, _ = worker_with_db
        result = worker._effective("delete_source", None)
        from config import settings
        assert result == settings.delete_source

    def test_effective_key_not_in_overrides(self, worker_with_db):
        """Cover _effective: key not in overrides dict."""
        worker, _ = worker_with_db
        result = worker._effective("delete_source", {"output_extension": "mp4"})
        from config import settings
        assert result == settings.delete_source
