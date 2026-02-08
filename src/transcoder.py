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
from constants import AUDIO_FILE_EXTENSIONS
from database import get_db
from models import TranscodeJobDB, JobStatus, TranscodeJob

logger = logging.getLogger(__name__)


def check_gpu_support() -> dict:
    """Check which GPU encoders are available (NVENC, VAAPI, AMF, QSV)."""
    result = {
        "handbrake_nvenc": False,
        "ffmpeg_nvenc_h265": False,
        "ffmpeg_nvenc_h264": False,
        "ffmpeg_vaapi_h265": False,
        "ffmpeg_vaapi_h264": False,
        "ffmpeg_amf_h265": False,
        "ffmpeg_amf_h264": False,
        "ffmpeg_qsv_h265": False,
        "ffmpeg_qsv_h264": False,
        "vaapi_device": False,
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

    # Check FFmpeg encoders (NVENC, VAAPI, AMF, QSV)
    try:
        output = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, timeout=10
        )
        stdout = output.stdout
        # NVENC (NVIDIA)
        if "hevc_nvenc" in stdout:
            result["ffmpeg_nvenc_h265"] = True
        if "h264_nvenc" in stdout:
            result["ffmpeg_nvenc_h264"] = True
        # VAAPI (AMD/Intel on Linux)
        if "hevc_vaapi" in stdout:
            result["ffmpeg_vaapi_h265"] = True
        if "h264_vaapi" in stdout:
            result["ffmpeg_vaapi_h264"] = True
        # AMF (AMD)
        if "hevc_amf" in stdout:
            result["ffmpeg_amf_h265"] = True
        if "h264_amf" in stdout:
            result["ffmpeg_amf_h264"] = True
        # QSV (Intel Quick Sync)
        if "hevc_qsv" in stdout:
            result["ffmpeg_qsv_h265"] = True
        if "h264_qsv" in stdout:
            result["ffmpeg_qsv_h264"] = True
    except Exception:
        pass

    # Check for VAAPI/QSV device (typically /dev/dri/renderD128)
    vaapi_device = os.environ.get("VAAPI_DEVICE", "/dev/dri/renderD128")
    if os.path.exists(vaapi_device):
        result["vaapi_device"] = True

    return result


# Keep backward-compatible alias
check_nvenc_support = check_gpu_support


class TranscodeWorker:
    """Background worker that processes transcode jobs."""

    def __init__(self):
        self._queue: asyncio.Queue[TranscodeJob] = asyncio.Queue()
        self._running = False
        self._current_job: Optional[str] = None
        self._shutdown_event = asyncio.Event()
        self._gpu_support = check_gpu_support()

        logger.info(f"GPU support: {self._gpu_support}")

        # Determine encoder family from settings
        encoder = settings.video_encoder
        self._encoder_family = self._detect_encoder_family(encoder)
        self._encoder_backend = self._select_backend(encoder, self._encoder_family)

        logger.info(f"Encoder family: {self._encoder_family}, backend: {self._encoder_backend}")

    def _detect_encoder_family(self, encoder: str) -> str:
        """Determine encoder family from encoder name."""
        if "vaapi" in encoder:
            return "vaapi"
        if "amf" in encoder:
            return "amf"
        if "nvenc" in encoder:
            return "nvenc"
        if "qsv" in encoder:
            return "qsv"
        if encoder in ("x265", "x264"):
            return "software"
        return "unknown"

    def _select_backend(self, encoder: str, family: str) -> str:
        """Select transcoding backend (handbrake or ffmpeg) based on encoder."""
        if family == "nvenc":
            if self._gpu_support["handbrake_nvenc"]:
                logger.info("Using HandBrake with NVENC")
                return "handbrake"
            elif self._gpu_support["ffmpeg_nvenc_h265"] or self._gpu_support["ffmpeg_nvenc_h264"]:
                logger.info("Using FFmpeg with NVENC")
                return "ffmpeg"
            else:
                logger.warning("NVENC not detected - will attempt FFmpeg anyway")
                return "ffmpeg"
        elif family == "vaapi":
            if not self._gpu_support["vaapi_device"]:
                logger.warning("VAAPI device not found at /dev/dri/renderD128 - encoding may fail")
            logger.info("Using FFmpeg with VAAPI (AMD/Intel)")
            return "ffmpeg"
        elif family == "amf":
            logger.info("Using FFmpeg with AMF (AMD)")
            return "ffmpeg"
        elif family == "qsv":
            logger.info("Using FFmpeg with Quick Sync (Intel)")
            return "ffmpeg"
        elif family == "software":
            logger.info("Using FFmpeg with software encoding")
            return "ffmpeg"
        else:
            logger.info("Using HandBrake (default backend)")
            return "handbrake"

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
        """Process a single transcode job.

        Uses local scratch storage (work_path) to avoid doing heavy I/O on NFS:
          1. Copy source from NFS raw → local work dir
          2. Transcode locally
          3. Move output from local → NFS completed
          4. Clean up local work dir (always, even on failure)
          5. Clean up NFS raw source (if delete_source is set)
        """
        logger.info(f"Processing job {job.id}: {job.title}")

        async with get_db() as db:
            result = await db.execute(
                select(TranscodeJobDB).where(TranscodeJobDB.id == job.id)
            )
            job_db = result.scalar_one()

            # Local scratch directory for this job
            work_job_dir = Path(settings.work_path) / f"job-{job.id}"

            try:
                # Update status to processing
                job_db.status = JobStatus.PROCESSING
                job_db.started_at = datetime.utcnow()
                await db.commit()

                # Wait for source to stabilize (files still being written)
                await self._wait_for_stable(job.source_path)

                # Discover source files on NFS
                source_files = self._discover_source_files(job.source_path)
                if not source_files:
                    # Check for audio files (music CD rip)
                    audio_files = self._discover_audio_files(job.source_path)
                    if audio_files:
                        await self._passthrough_audio(job, job_db, db)
                        return
                    raise ValueError(f"No video or audio files found in {job.source_path}")

                job_db.total_tracks = len(source_files)
                await db.commit()

                logger.info(f"Found {len(source_files)} MKV files to transcode")

                # Copy source from NFS to local scratch
                work_source_dir = work_job_dir / "source"
                work_output_dir = work_job_dir / "output"
                source = Path(job.source_path)

                work_job_dir.mkdir(parents=True, exist_ok=True)
                work_output_dir.mkdir()

                logger.info(f"Copying source to local scratch: {work_source_dir}")
                if source.is_file():
                    work_source_dir.mkdir()
                    shutil.copy2(str(source), str(work_source_dir / source.name))
                else:
                    shutil.copytree(str(source), str(work_source_dir))

                # Re-discover files from local copy
                local_source_files = self._discover_source_files(str(work_source_dir))

                # Determine final NFS output path
                output_dir = self._determine_output_path(job.title, job.source_path)
                os.makedirs(output_dir, exist_ok=True)
                job_db.output_path = str(output_dir)
                await db.commit()

                # Find main feature (largest file)
                main_feature = max(local_source_files, key=lambda f: f.stat().st_size)
                job_db.main_feature_file = main_feature.name
                await db.commit()

                # Transcode each file locally
                for i, source_file in enumerate(local_source_files):
                    progress = (i / len(local_source_files)) * 100
                    job_db.progress = progress
                    await db.commit()

                    output_file = work_output_dir / f"{source_file.stem}.{settings.output_extension}"

                    # Determine if this is the main feature
                    is_main = source_file == main_feature

                    logger.info(
                        f"Transcoding [{i+1}/{len(local_source_files)}]: {source_file.name}"
                        f"{' (main feature)' if is_main else ''}"
                    )

                    if self._encoder_backend == "ffmpeg":
                        await self._transcode_file_ffmpeg(source_file, output_file, job_db, db)
                    else:
                        await self._transcode_file_handbrake(source_file, output_file, job_db, db)

                # Move local output → NFS completed
                logger.info(f"Moving output to completed: {output_dir}")
                for f in work_output_dir.iterdir():
                    shutil.move(str(f), str(output_dir / f.name))

                # Success
                job_db.status = JobStatus.COMPLETED
                job_db.progress = 100.0
                job_db.completed_at = datetime.utcnow()
                await db.commit()

                # Clean up NFS raw source if configured
                if settings.delete_source:
                    self._cleanup_source(job.source_path)
                    logger.info(f"Cleaned up source: {job.source_path}")

                logger.info(f"Completed job {job.id}: {job.title}")

            except Exception as e:
                logger.error(f"Job {job.id} failed: {e}", exc_info=True)
                job_db.status = JobStatus.FAILED
                job_db.error = str(e)
                await db.commit()

            finally:
                # Always clean up local scratch
                if work_job_dir.exists():
                    shutil.rmtree(work_job_dir)
                    logger.info(f"Cleaned up work dir: {work_job_dir}")

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

    def _discover_audio_files(self, source_path: str) -> list[Path]:
        """Find all audio files in source directory."""
        path = Path(source_path)

        if path.is_file():
            return [path] if path.suffix.lower() in AUDIO_FILE_EXTENSIONS else []

        audio_files = [
            f for f in path.iterdir()
            if f.is_file() and f.suffix.lower() in AUDIO_FILE_EXTENSIONS
        ]
        audio_files.sort(key=lambda f: f.name)

        return audio_files

    async def _passthrough_audio(
        self,
        job: TranscodeJob,
        job_db: TranscodeJobDB,
        db,
    ):
        """Move audio files directly to music output folder (no transcoding)."""
        clean_title = re.sub(r'[<>:"/\\|?*]', '', job.title)
        output_dir = Path(settings.completed_path) / settings.music_subdir / clean_title
        os.makedirs(output_dir, exist_ok=True)

        source = Path(job.source_path)
        audio_files = self._discover_audio_files(job.source_path)

        logger.info(f"Music passthrough: copying {len(audio_files)} audio files to {output_dir}")

        for f in audio_files:
            shutil.copy2(str(f), str(output_dir / f.name))

        job_db.output_path = str(output_dir)
        job_db.total_tracks = len(audio_files)
        job_db.status = JobStatus.COMPLETED
        job_db.progress = 100.0
        job_db.completed_at = datetime.utcnow()
        await db.commit()

        logger.info(f"Completed music passthrough for job {job.id}: {job.title}")

        # Clean up source directory if delete_source is set (non-fatal)
        if settings.delete_source:
            try:
                self._cleanup_source(job.source_path)
                logger.info(f"Cleaned up source: {job.source_path}")
            except OSError as e:
                logger.warning(f"Could not clean up source {job.source_path}: {e}")

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

    def _build_ffmpeg_command(self, source: Path, output: Path) -> list[str]:
        """Build FFmpeg command based on encoder family."""
        encoder_name = settings.video_encoder
        family = self._encoder_family
        quality = settings.video_quality

        # Determine FFmpeg encoder name
        if family == "nvenc":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_nvenc"
            else:
                ffmpeg_encoder = "h264_nvenc"
        elif family == "vaapi":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_vaapi"
            else:
                ffmpeg_encoder = "h264_vaapi"
        elif family == "amf":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_amf"
            else:
                ffmpeg_encoder = "h264_amf"
        elif family == "qsv":
            if "h265" in encoder_name or "hevc" in encoder_name:
                ffmpeg_encoder = "hevc_qsv"
            else:
                ffmpeg_encoder = "h264_qsv"
        elif family == "software":
            if encoder_name == "x265":
                ffmpeg_encoder = "libx265"
            else:
                ffmpeg_encoder = "libx264"
        else:
            ffmpeg_encoder = encoder_name

        cmd = ["ffmpeg", "-y"]

        # Hardware acceleration input flags (per encoder family)
        if family == "nvenc":
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
        elif family == "vaapi":
            vaapi_device = os.environ.get("VAAPI_DEVICE", "/dev/dri/renderD128")
            cmd.extend([
                "-hwaccel", "vaapi",
                "-hwaccel_device", vaapi_device,
                "-hwaccel_output_format", "vaapi",
            ])
        elif family == "qsv":
            cmd.extend(["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"])

        # Input file
        cmd.extend(["-i", str(source)])

        # Video encoder
        cmd.extend(["-c:v", ffmpeg_encoder])

        # Quality settings (per encoder family)
        if family == "nvenc":
            cmd.extend(["-preset", "p4", "-cq", str(quality), "-b:v", "0"])
        elif family == "vaapi":
            cmd.extend(["-rc_mode", "CQP", "-qp", str(quality)])
        elif family == "amf":
            cmd.extend(["-rc", "cqp", "-qp_i", str(quality), "-qp_p", str(quality)])
        elif family == "qsv":
            cmd.extend(["-global_quality", str(quality)])
        elif family == "software":
            cmd.extend(["-crf", str(quality), "-preset", "medium"])

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

        return cmd

    async def _transcode_file_ffmpeg(
        self,
        source: Path,
        output: Path,
        job_db: TranscodeJobDB,
        db,
    ):
        """Transcode a single file using FFmpeg."""
        cmd = self._build_ffmpeg_command(source, output)

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
