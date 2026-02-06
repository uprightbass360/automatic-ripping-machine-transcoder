"""
ARM Transcoder - Webhook receiver and transcode orchestrator
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, Request
from fastapi.responses import JSONResponse

from config import settings
from database import init_db, get_db
from models import WebhookPayload, JobStatus, TranscodeJob
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
    background_tasks: BackgroundTasks,
    x_webhook_secret: str | None = Header(None, alias="X-Webhook-Secret"),
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
    # Validate webhook secret if configured
    if settings.webhook_secret:
        if x_webhook_secret != settings.webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    logger.info(f"Received webhook: {payload}")

    # Parse the payload
    title = payload.get("title", "")
    body = payload.get("body", "")
    path = payload.get("path")
    job_id = payload.get("job_id")

    # Check if this is a completion notification
    is_complete = (
        "complete" in title.lower() or
        "complete" in body.lower() or
        payload.get("status") == "success"
    )

    if not is_complete:
        logger.debug(f"Ignoring non-completion webhook: {title}")
        return {"status": "ignored", "reason": "not a completion event"}

    # Extract path from body if not provided directly
    if not path and body:
        # Try to extract path from ARM notification body
        # Format: "Rip of Movie Title (2024) complete"
        import re
        match = re.search(r"Rip of (.+?) complete", body)
        if match:
            title_from_body = match.group(1)
            path = f"{settings.raw_path}/{title_from_body}"

    if not path:
        logger.warning(f"Could not determine path from webhook: {payload}")
        return {"status": "error", "reason": "could not determine source path"}

    # Queue the transcode job
    await worker.queue_job(
        source_path=path,
        title=title or payload.get("title", "Unknown"),
        arm_job_id=job_id,
    )

    return {
        "status": "queued",
        "path": path,
        "queue_size": worker.queue_size,
    }


@app.get("/jobs")
async def list_jobs(status: JobStatus | None = None):
    """List all transcode jobs, optionally filtered by status."""
    async with get_db() as db:
        from sqlalchemy import select
        from models import TranscodeJobDB

        query = select(TranscodeJobDB)
        if status:
            query = query.where(TranscodeJobDB.status == status)
        query = query.order_by(TranscodeJobDB.created_at.desc())

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
            ]
        }


@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int):
    """Retry a failed job."""
    async with get_db() as db:
        from sqlalchemy import select
        from models import TranscodeJobDB

        result = await db.execute(
            select(TranscodeJobDB).where(TranscodeJobDB.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        if job.status != JobStatus.FAILED:
            raise HTTPException(status_code=400, detail="Job is not in failed state")

        # Reset job status
        job.status = JobStatus.PENDING
        job.error = None
        job.progress = 0
        await db.commit()

        # Re-queue
        await worker.queue_job(
            source_path=job.source_path,
            title=job.title,
            arm_job_id=job.arm_job_id,
            existing_job_id=job.id,
        )

        return {"status": "queued", "job_id": job.id}


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: int):
    """Delete a job from the database."""
    async with get_db() as db:
        from sqlalchemy import select, delete
        from models import TranscodeJobDB

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
async def get_stats():
    """Get transcoding statistics."""
    async with get_db() as db:
        from sqlalchemy import select, func
        from models import TranscodeJobDB

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
            "worker_running": worker is not None and worker.is_running,
            "current_job": worker.current_job if worker else None,
        }
