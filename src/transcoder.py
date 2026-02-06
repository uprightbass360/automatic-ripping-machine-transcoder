"""
Transcode worker - handles GPU transcoding with HandBrake or FFmpeg
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from config import settings
from database import get_db
from models import TranscodeJobDB, JobStatus, TranscodeJob

logger = logging.getLogger(__name__)


def check_nvenc_support() -> dict:
    """Check which NVENC encoders are available."""
    result = {
        "handbrake_nvenc": False,
        "ffmpeg_nvenc_h265": False,
        "ffmpeg_nvenc_h264": False,
    }

    # Check HandBrake NVENC
    try:
        output = subprocess.run(
            ["HandBrakeCLI", "--help"],
            capture_output=True, text=True, timeout=10
        )
        if "nvenc" in output.stdout.lower() or "nvenc" in output.stderr.lower():
            result["handbrake_nvenc"] = True
    except Exception:
        pass

    # Check FFmpeg NVENC
    try:
        output = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, timeout=10
        )
        if "hevc_nvenc" in output.stdout:
            result["ffmpeg_nvenc_h265"] = True
        if "h264_nvenc" in output.stdout:
            result["ffmpeg_nvenc_h264"] = True
    except Exception:
        pass

    return result


class TranscodeWorker:
    """Background worker that processes transcode jobs."""

    def __init__(self):
        self._queue: asyncio.Queue[TranscodeJob] = asyncio.Queue()
        self._running = False
        self._current_job: Optional[str] = None
        self._shutdown_event = asyncio.Event()
        self._nvenc_support = check_nvenc_support()

        logger.info(f"NVENC support: {self._nvenc_support}")

        # Determine which encoder to use
        if settings.video_encoder.startswith("nvenc"):
            if self._nvenc_support["handbrake_nvenc"]:
                self._encoder_backend = "handbrake"
                logger.info("Using HandBrake with NVENC")
            elif self._nvenc_support["ffmpeg_nvenc_h265"] or self._nvenc_support["ffmpeg_nvenc_h264"]:
                self._encoder_backend = "ffmpeg"
                logger.info("Using FFmpeg with NVENC (HandBrake NVENC not available)")
            else:
                self._encoder_backend = "ffmpeg"
                logger.warning("NVENC not detected - will attempt FFmpeg anyway")
        else:
            self._encoder_backend = "handbrake"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def current_job(self) -> Optional[str]:
        return self._current_job

    def shutdown(self):
        """Signal worker to shutdown."""
        self._shutdown_event.set()

    async def queue_job(
        self,
        source_path: str,
        title: str,
        arm_job_id: Optional[str] = None,
        existing_job_id: Optional[int] = None,
    ):
        """Add a job to the transcode queue."""
        async with get_db() as db:
            if existing_job_id:
                # Retry existing job
                result = await db.execute(
                    select(TranscodeJobDB).where(TranscodeJobDB.id == existing_job_id)
                )
                job_db = result.scalar_one()
            else:
                # Create new job record
                job_db = TranscodeJobDB(
                    title=title,
                    source_path=source_path,
                    arm_job_id=arm_job_id,
                    status=JobStatus.PENDING,
                )
                db.add(job_db)
                await db.commit()
                await db.refresh(job_db)

            job = TranscodeJob(
                id=job_db.id,
                title=title,
                source_path=source_path,
                arm_job_id=arm_job_id,
            )

        await self._queue.put(job)
        logger.info(f"Queued job {job.id}: {title}")

    async def run(self):
        """Main worker loop."""
        self._running = True
        logger.info("Transcode worker started")

        # Load any pending jobs from database on startup
        await self._load_pending_jobs()

        while not self._shutdown_event.is_set():
            try:
                # Wait for a job with timeout to allow shutdown checks
                try:
                    job = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                self._current_job = job.title
                await self._process_job(job)
                self._current_job = None
                self._queue.task_done()

            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                await asyncio.sleep(5)

        self._running = False
        logger.info("Transcode worker stopped")

    async def _load_pending_jobs(self):
        """Load any pending jobs from database on startup."""
        async with get_db() as db:
            result = await db.execute(
                select(TranscodeJobDB)
                .where(TranscodeJobDB.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]))
                .order_by(TranscodeJobDB.created_at)
            )
            jobs = result.scalars().all()

            for job_db in jobs:
                # Reset processing jobs to pending
                if job_db.status == JobStatus.PROCESSING:
                    job_db.status = JobStatus.PENDING
                    await db.commit()

                job = TranscodeJob(
                    id=job_db.id,
                    title=job_db.title,
                    source_path=job_db.source_path,
                    arm_job_id=job_db.arm_job_id,
                )
                await self._queue.put(job)
                logger.info(f"Restored pending job {job.id}: {job.title}")

    async def _process_job(self, job: TranscodeJob):
        """Process a single transcode job."""
        logger.info(f"Processing job {job.id}: {job.title}")

        async with get_db() as db:
            result = await db.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job.id)
            )
            job_db = result.scalar_one()

            try:
                # Update status to processing
                job_db.status = JobStatus.PROCESSING
                job_db.started_at = datetime.utcnow()
                await db.commit()

                # Wait for source to stabilize (files still being written)
                await self._wait_for_stable(job.source_path)

                # Discover source files
                source_files = self._discover_source_files(job.source_path)
                if not source_files:
                    raise ValueError(f"No MKV files found in {job.source_path}")

                job_db.total_tracks = len(source_files)
                await db.commit()

                logger.info(f"Found {len(source_files)} MKV files to transcode")

                # Determine output path
                output_dir = self._determine_output_path(job.title, job.source_path)
                os.makedirs(output_dir, exist_ok=True)
                job_db.output_path = str(output_dir)
                await db.commit()

                # Find main feature (largest file)
                main_feature = max(source_files, key=lambda f: f.stat().st_size)
                job_db.main_feature_file = main_feature.name
                await db.commit()

                # Transcode each file
                for i, source_file in enumerate(source_files):
                    progress = (i / len(source_files)) * 100
                    job_db.progress = progress
                    await db.commit()

                    output_file = output_dir / f"{source_file.stem}.{settings.output_extension}"

                    # Determine if this is the main feature
                    is_main = source_file == main_feature

                    logger.info(
                        f"Transcoding [{i+1}/{len(source_files)}]: {source_file.name}"
                        f"{' (main feature)' if is_main else ''}"
                    )

                    if self._encoder_backend == "ffmpeg":
                        await self._transcode_file_ffmpeg(source_file, output_file, job_db, db)
                    else:
                        await self._transcode_file_handbrake(source_file, output_file, job_db, db)

                # Success - clean up source if configured
                job_db.status = JobStatus.COMPLETED
                job_db.progress = 100.0
                job_db.completed_at = datetime.utcnow()
                await db.commit()

                if settings.delete_source:
                    self._cleanup_source(job.source_path)
                    logger.info(f"Cleaned up source: {job.source_path}")

                logger.info(f"Completed job {job.id}: {job.title}")

            except Exception as e:
                logger.error(f"Job {job.id} failed: {e}", exc_info=True)
                job_db.status = JobStatus.FAILED
                job_db.error = str(e)
                await db.commit()

    async def _wait_for_stable(self, path: str, timeout: int = 3600):
        """Wait for directory to stop receiving new files."""
        path = Path(path)
        if not path.exists():
            raise ValueError(f"Source path does not exist: {path}")

        logger.info(f"Waiting for source to stabilize: {path}")

        last_size = -1
        stable_time = 0
        start_time = asyncio.get_event_loop().time()

        while stable_time < settings.stabilize_seconds:
            current_size = sum(
                f.stat().st_size for f in path.rglob('*') if f.is_file()
            )

            if current_size == last_size:
                stable_time += 5
            else:
                stable_time = 0
                last_size = current_size

            await asyncio.sleep(5)

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"Source still changing after {timeout}s")

        logger.info(f"Source stabilized at {last_size} bytes")

    def _discover_source_files(self, source_path: str) -> list[Path]:
        """Find all MKV files in source directory."""
        path = Path(source_path)

        if path.is_file():
            return [path] if path.suffix.lower() == '.mkv' else []

        # Find all MKV files, sorted by size (largest first)
        mkv_files = list(path.glob("*.mkv"))
        mkv_files.sort(key=lambda f: f.stat().st_size, reverse=True)

        return mkv_files

    def _determine_output_path(self, title: str, source_path: str) -> Path:
        """Determine the output directory path."""
        # For now, assume movies - could be enhanced with metadata lookup
        base = Path(settings.completed_path) / settings.movies_subdir

        # Clean title for filesystem
        clean_title = re.sub(r'[<>:"/\\|?*]', '', title)

        return base / clean_title

    async def _transcode_file_handbrake(
        self,
        source: Path,
        output: Path,
        job_db: TranscodeJobDB,
        db,
    ):
        """Transcode a single file using HandBrake."""
        cmd = [
            "HandBrakeCLI",
            "-i", str(source),
            "-o", str(output),
        ]

        # Add encoder
        if settings.video_encoder:
            cmd.extend(["--encoder", settings.video_encoder])

        # Add quality
        cmd.extend(["-q", str(settings.video_quality)])

        # Add preset if specified
        if settings.handbrake_preset_file:
            cmd.extend(["--preset-import-file", settings.handbrake_preset_file])
        if settings.handbrake_preset:
            cmd.extend(["--preset", settings.handbrake_preset])

        # Audio handling
        if settings.audio_encoder == "copy":
            cmd.extend(["--aencoder", "copy"])
        else:
            cmd.extend(["--aencoder", settings.audio_encoder])

        # Subtitle handling
        if settings.subtitle_mode == "all":
            cmd.extend(["--all-subtitles"])
        elif settings.subtitle_mode == "first":
            cmd.extend(["--subtitle", "1"])

        logger.debug(f"HandBrake command: {' '.join(cmd)}")

        # Run HandBrake and parse progress
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Parse output for progress
        async for line in process.stdout:
            line = line.decode('utf-8', errors='replace').strip()

            # Parse HandBrake progress: "Encoding: task 1 of 1, 45.23 %"
            match = re.search(r'(\d+\.?\d*)\s*%', line)
            if match:
                file_progress = float(match.group(1))
                # Update database periodically (every 5%)
                if int(file_progress) % 5 == 0:
                    job_db.progress = file_progress
                    await db.commit()

        await process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"HandBrake failed with exit code {process.returncode}")

        # Verify output exists
        if not output.exists():
            raise RuntimeError(f"Output file was not created: {output}")

        logger.info(f"Transcoded: {source.name} -> {output.name}")

    async def _transcode_file_ffmpeg(
        self,
        source: Path,
        output: Path,
        job_db: TranscodeJobDB,
        db,
    ):
        """Transcode a single file using FFmpeg with NVENC."""

        # Determine encoder
        if "h265" in settings.video_encoder or "hevc" in settings.video_encoder:
            encoder = "hevc_nvenc"
        else:
            encoder = "h264_nvenc"

        # Map quality to CQ (constant quality) for NVENC
        # HandBrake quality ~20-24 maps roughly to NVENC CQ 20-28
        cq = settings.video_quality

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-hwaccel", "cuda",  # Use CUDA for decoding too
            "-hwaccel_output_format", "cuda",
            "-i", str(source),
            "-c:v", encoder,
            "-preset", "p4",  # NVENC preset (p1=fastest, p7=slowest)
            "-cq", str(cq),  # Constant quality mode
            "-b:v", "0",  # Required for CQ mode
        ]

        # Audio handling
        if settings.audio_encoder == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", settings.audio_encoder])

        # Subtitle handling
        if settings.subtitle_mode == "all":
            cmd.extend(["-c:s", "copy"])
        elif settings.subtitle_mode == "none":
            cmd.extend(["-sn"])
        else:
            cmd.extend(["-map", "0:s:0?", "-c:s", "copy"])

        # Output
        cmd.append(str(output))

        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        # Run FFmpeg and parse progress
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Get duration for progress calculation
        duration = await self._get_video_duration(source)

        async for line in process.stdout:
            line = line.decode('utf-8', errors='replace').strip()

            # Parse FFmpeg progress: "time=00:01:23.45"
            match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
            if match and duration:
                hours, mins, secs = match.groups()
                current_secs = int(hours) * 3600 + int(mins) * 60 + float(secs)
                file_progress = min(100, (current_secs / duration) * 100)
                if int(file_progress) % 5 == 0:
                    job_db.progress = file_progress
                    await db.commit()

        await process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed with exit code {process.returncode}")

        if not output.exists():
            raise RuntimeError(f"Output file was not created: {output}")

        logger.info(f"Transcoded: {source.name} -> {output.name}")

    async def _get_video_duration(self, path: Path) -> Optional[float]:
        """Get video duration in seconds using ffprobe."""
        try:
            result = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await result.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return None

    def _cleanup_source(self, source_path: str):
        """Remove source files after successful transcode."""
        path = Path(source_path)

        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
