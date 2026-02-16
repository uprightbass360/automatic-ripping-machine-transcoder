"""
Shared fixtures for ARM Transcoder tests.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Set test environment variables before importing app modules
os.environ.setdefault("RAW_PATH", "/tmp/test_raw")
os.environ.setdefault("COMPLETED_PATH", "/tmp/test_completed")
os.environ.setdefault("WORK_PATH", "/tmp/test_work")
os.environ.setdefault("DB_PATH", "/tmp/test_transcoder.db")
os.environ.setdefault("REQUIRE_API_AUTH", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_PATH", "/tmp/test_transcoder_logs")


@pytest.fixture
def tmp_dirs(tmp_path):
    """Create temporary directory structure for tests."""
    raw = tmp_path / "raw"
    completed = tmp_path / "completed"
    work = tmp_path / "work"
    db_dir = tmp_path / "db"

    for d in [raw, completed, work, db_dir]:
        d.mkdir()

    return {
        "root": tmp_path,
        "raw": raw,
        "completed": completed,
        "work": work,
        "db_dir": db_dir,
        "db_path": str(db_dir / "test.db"),
    }


@pytest.fixture
def sample_mkv_dir(tmp_dirs):
    """Create a sample directory with fake MKV files."""
    movie_dir = tmp_dirs["raw"] / "Test Movie (2024)"
    movie_dir.mkdir()

    # Create fake MKV files of different sizes
    main_feature = movie_dir / "title_main.mkv"
    main_feature.write_bytes(b"\x00" * 10000)  # 10KB "main feature"

    extra = movie_dir / "title_extra.mkv"
    extra.write_bytes(b"\x00" * 2000)  # 2KB "extra"

    return {
        "dir": movie_dir,
        "main_feature": main_feature,
        "extra": extra,
    }


@pytest.fixture
def path_validator(tmp_dirs):
    """Create a PathValidator with test directories."""
    from utils import PathValidator

    return PathValidator([str(tmp_dirs["raw"]), str(tmp_dirs["completed"])])


@pytest_asyncio.fixture
async def test_db(tmp_dirs):
    """Create a test database with async engine."""
    from models import Base

    db_url = f"sqlite+aiosqlite:///{tmp_dirs['db_path']}"
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine, session_factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for HandBrake/FFmpeg calls."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.__aiter__ = lambda self: self
    mock_proc.stdout.__anext__ = AsyncMock(side_effect=StopAsyncIteration)
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.communicate = AsyncMock(return_value=(b"3600.0", b""))
    return mock_proc
