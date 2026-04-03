"""
ARM Transcoder - Webhook receiver and transcode orchestrator

Endpoints in src/routers/ — health.py, config.py, jobs.py, stats.py, logs.py
"""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog

from fastapi import FastAPI

from config import settings, load_config_overrides, auto_resolve_gpu_defaults
from constants import SHUTDOWN_TIMEOUT
from database import init_db
from log_format import _foreign_pre_chain, json_formatter, console_formatter
from gpu_monitor import create_gpu_monitor
from transcoder import TranscodeWorker

from routers.health import router as health_router
from routers.config import router as config_router
from routers.jobs import router as jobs_router
from routers.stats import router as stats_router
from routers.logs import router as logs_router
from routers.workers import router as workers_router


def _configure_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )

    log_level = getattr(logging, settings.log_level)
    root = logging.getLogger()
    root.setLevel(log_level)

    # Third-party loggers at a separate (usually higher) level
    lib_level = getattr(logging, settings.log_level_libraries)
    for name in ("aiosqlite", "httpcore", "httpx", "uvicorn.access"):
        logging.getLogger(name).setLevel(lib_level)

    # Console: colored human-readable (for docker logs)
    console = logging.StreamHandler()
    console.setFormatter(console_formatter())
    root.addHandler(console)

    # File: JSON lines (machine-parseable)
    log_dir = Path(settings.log_path)
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        log_dir / "transcoder.log", maxBytes=10_485_760, backupCount=5
    )
    fh.setFormatter(json_formatter())
    root.addHandler(fh)


_configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Initialize database
    await init_db()

    # Apply any persisted config overrides
    await load_config_overrides()

    # Probe GPU, auto-resolve defaults, then start worker with resolved settings
    from transcoder import check_gpu_support
    gpu_support = check_gpu_support()
    await auto_resolve_gpu_defaults(gpu_support)

    app.state.worker = TranscodeWorker(gpu_support=gpu_support)

    # Spawn max_concurrent worker tasks pulling from the shared queue
    n_workers = settings.max_concurrent
    worker_tasks = []
    for i in range(n_workers):
        task = asyncio.create_task(app.state.worker.run(worker_id=i))
        worker_tasks.append(task)
    logger.info("Started %d worker(s)", n_workers)

    app.state.gpu_monitor = create_gpu_monitor(settings.gpu_vendor)
    if app.state.gpu_monitor:
        logger.info("GPU monitor active: %s", settings.gpu_vendor)

    logger.info("ARM Transcoder started")

    yield

    # Shutdown: send sentinel per worker, then wait for all to finish
    worker = app.state.worker
    if worker:
        worker.shutdown()
        for _ in worker_tasks:
            await worker.queue_sentinel()
        for task in worker_tasks:
            try:
                await asyncio.wait_for(task, timeout=SHUTDOWN_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Worker did not finish within %ds, cancelling", SHUTDOWN_TIMEOUT)
                task.cancel()
            except asyncio.CancelledError:
                raise
    else:
        for task in worker_tasks:
            task.cancel()

    logger.info("ARM Transcoder stopped")


def _read_version() -> str:
    for p in (
        "VERSION",
        os.path.join(os.path.dirname(__file__), "VERSION"),
        os.path.join(os.path.dirname(__file__), "..", "VERSION"),
        "/etc/arm-transcoder-version",
    ):
        try:
            with open(p) as f:
                return f.read().strip()
        except OSError:
            continue
    return "unknown"


APP_VERSION = _read_version()

app = FastAPI(
    title="ARM Transcoder",
    description="GPU-accelerated transcoding service for Automatic Ripping Machine",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(config_router)
app.include_router(jobs_router)
app.include_router(stats_router)
app.include_router(logs_router)
app.include_router(workers_router)
