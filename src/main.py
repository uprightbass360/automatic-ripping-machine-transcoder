"""
ARM Transcoder - Webhook receiver and transcode orchestrator
"""

import asyncio
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, delete, func

from auth import get_current_user, require_admin, verify_webhook_secret
from config import settings
from database import init_db, get_db
from models import WebhookPayload, JobStatus, TranscodeJob, TranscodeJobDB
from transcoder import TranscodeWorker

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global worker instance
worker: TranscodeWorker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    global worker

    # Initialize database
    await init_db()

    # Start the transcode worker
    worker = TranscodeWorker()
    worker_task = asyncio.create_task(worker.run())

    logger.info("ARM Transcoder started")

    yield

    # Shutdown
    if worker:
        worker.shutdown()
    worker_task.cancel()

    logger.info("ARM Transcoder stopped")


app = FastAPI(
    title="ARM Transcoder",
    description="GPU-accelerated transcoding service for Automatic Ripping Machine",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "worker_running": worker is not None and worker.is_running,
        "queue_size": worker.queue_size if worker else 0,
    }


@app.post("/webhook/arm")
async def arm_webhook(
    request: Request,
    _verified: bool = Depends(verify_webhook_secret),
):
    """
    Receive webhook from ARM's JSON_URL or BASH_SCRIPT curl.

    Expected payload formats:

    1. Apprise JSON format:
    {
        "title": "ARM notification",
        "body": "Rip of Movie Title (2024) complete",
        "type": "info"
    }

    2. Custom format from BASH_SCRIPT:
    {
        "title": "Movie Title",
        "path": "/home/arm/media/raw/Movie Title (2024)",
        "job_id": "123",
        "status": "success"
    }
    """
    # Validate request size (10KB limit)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10240:  # 10KB
        raise HTTPException(status_code=413, detail="Payload too large (max 10KB)")

    try:
        payload_dict = await request.json()
        # Validate with Pydantic model
        payload = WebhookPayload(**payload_dict)
    except Exception as e:
        logger.warning(f"Invalid webhook payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    # Use effective_body which handles both 'body' (curl) and 'message' (Apprise) fields
    body = payload.effective_body
    logger.info(f"Received webhook: {payload.title} (body={'present' if body else 'empty'})")

    # Check if this is a completion notification
    is_complete = (
        "complete" in payload.title.lower() or
        (body and "complete" in body.lower()) or
        payload.status == "success"
    )

    if not is_complete:
        logger.debug(f"Ignoring non-completion webhook: {payload.title}")
        return {"status": "ignored", "reason": "not a completion event"}

    # Determine source path
    source_path = payload.path

    # Extract title from body if path not provided directly
    if not source_path and body:
        # ARM notification formats:
        #   "{title} rip complete. Starting transcode."  (NOTIFY_RIP)
        #   "{title} processing complete."               (NOTIFY_TRANSCODE)
        #   "Rip of {title} complete"                    (legacy/custom)
        title_from_body = None
        for pattern in [
            r"^(.+?)\s+rip complete",           # ARM rip notification
            r"^(.+?)\s+processing complete",     # ARM transcode notification
            r"Rip of (.+?) complete",            # legacy format
        ]:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                title_from_body = match.group(1).strip()
                break

        if title_from_body:
            # Security: Only use the filename part, not full path
            from pathlib import Path
            safe_title = Path(title_from_body).name
            source_path = safe_title

    if not source_path:
        logger.warning(f"Could not determine path from webhook: {payload.title}")
        return {"status": "error", "reason": "could not determine source path"}

    # Security: Validate path is just a directory name (no traversal)
    from pathlib import Path
    if "/" in source_path or "\\" in source_path or ".." in source_path:
        logger.warning(f"Rejected path with traversal attempt: {source_path}")
        return {"status": "error", "reason": "invalid path"}

    # Construct full path within RAW_PATH
    full_path = str(Path(settings.raw_path) / source_path)

    # Queue the transcode job
    await worker.queue_job(
        source_path=full_path,
        title=payload.title,
        arm_job_id=payload.job_id,
    )

    return {
        "status": "queued",
        "path": source_path,
        "queue_size": worker.queue_size,
    }


@app.get("/jobs")
async def list_jobs(
    status: JobStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    _role: str = Depends(get_current_user),
):
    """List all transcode jobs, optionally filtered by status."""
    # Validate pagination
    if limit > 500:
        limit = 500
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0

    async with get_db() as db:
        query = select(TranscodeJobDB)
        if status:
            query = query.where(TranscodeJobDB.status == status)
        query = query.order_by(TranscodeJobDB.created_at.desc())

        # Get total count
        count_query = select(func.count()).select_from(TranscodeJobDB)
        if status:
            count_query = count_query.where(TranscodeJobDB.status == status)
        total_result = await db.execute(count_query)
        total = total_result.scalar()

        # Apply pagination
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        jobs = result.scalars().all()

        return {
            "jobs": [
                {
                    "id": job.id,
                    "title": job.title,
                    "source_path": job.source_path,
                    "status": job.status,
                    "progress": job.progress,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "error": job.error,
                }
                for job in jobs
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@app.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: int,
    _role: str = Depends(require_admin),
):
    """Retry a failed job (admin only)."""
    async with get_db() as db:
        result = await db.execute(
            select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status != JobStatus.FAILED:
            raise HTTPException(status_code=400, detail="Job is not in failed state")

        # Check retry limit
        if job.retry_count >= settings.max_retry_count:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum retry limit reached ({settings.max_retry_count})"
            )

        # Reset job status
        job.status = JobStatus.PENDING
        job.error = None
        job.progress = 0
        job.retry_count += 1
        await db.commit()

        # Re-queue
        await worker.queue_job(
            source_path=job.source_path,
            title=job.title,
            arm_job_id=job.arm_job_id,
            existing_job_id=job.id,
        )

        return {"status": "queued", "job_id": job.id, "retry_count": job.retry_count}


@app.delete("/jobs/{job_id}")
async def delete_job(
    job_id: int,
    _role: str = Depends(require_admin),
):
    """Delete a job from the database (admin only)."""
    async with get_db() as db:
        result = await db.execute(
            select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status == JobStatus.PROCESSING:
            raise HTTPException(status_code=400, detail="Cannot delete job in progress")

        await db.execute(delete(TranscodeJobDB).where(TranscodeJobDB.id == job_id))
        await db.commit()

        return {"status": "deleted", "job_id": job_id}


@app.get("/stats")
async def get_stats(_role: str = Depends(get_current_user)):
    """Get transcoding statistics."""
    async with get_db() as db:
        # Count by status
        result = await db.execute(
            select(TranscodeJobDB.status, func.count(TranscodeJobDB.id))
            .group_by(TranscodeJobDB.status)
        )
        status_counts = dict(result.all())

        return {
            "pending": status_counts.get(JobStatus.PENDING, 0),
            "processing": status_counts.get(JobStatus.PROCESSING, 0),
            "completed": status_counts.get(JobStatus.COMPLETED, 0),
            "failed": status_counts.get(JobStatus.FAILED, 0),
            "cancelled": status_counts.get(JobStatus.CANCELLED, 0),
            "worker_running": worker is not None and worker.is_running,
            "current_job": worker.current_job if worker else None,
        }
