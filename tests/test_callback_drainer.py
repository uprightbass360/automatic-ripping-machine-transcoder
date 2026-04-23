"""Unit tests for callback drainer components."""
import httpx
import pytest


# ── is_permanent_error ─────────────────────────────────────────────────

@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 422])
def test_permanent_error_for_terminal_4xx_codes(code):
    from callback_drainer import is_permanent_error
    response = httpx.Response(code)
    assert is_permanent_error(response) is True


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_retriable_for_non_terminal_error_codes(code):
    from callback_drainer import is_permanent_error
    response = httpx.Response(code)
    assert is_permanent_error(response) is False


@pytest.mark.parametrize("code", [200, 201, 202, 204])
def test_not_permanent_for_success_codes(code):
    """Success isn't classified as permanent failure; the caller checks
    status_code < 300 separately before reaching this function."""
    from callback_drainer import is_permanent_error
    response = httpx.Response(code)
    assert is_permanent_error(response) is False


def test_network_exception_is_retriable():
    from callback_drainer import is_permanent_error
    exc = httpx.ConnectError("refused")
    assert is_permanent_error(exc) is False


def test_timeout_exception_is_retriable():
    from callback_drainer import is_permanent_error
    exc = httpx.ReadTimeout("timed out")
    assert is_permanent_error(exc) is False


# ── backoff_seconds ─────────────────────────────────────────────────────

@pytest.mark.parametrize("attempt, expected", [
    (1, 5),
    (2, 10),
    (3, 20),
    (4, 40),
    (5, 80),
    (6, 160),
    (7, 320),
    (8, 640),
    (9, 1280),
    (10, 1800),
    (11, 1800),
    (100, 1800),
])
def test_backoff_schedule(attempt, expected):
    """Exponential 5s doubling, capped at 1800s (30 min). No ceiling on attempts."""
    from callback_drainer import backoff_seconds
    assert backoff_seconds(attempt) == expected


def test_backoff_zero_attempts_returns_zero():
    """Attempt 0 means 'send immediately'; used as the default for fresh rows."""
    from callback_drainer import backoff_seconds
    assert backoff_seconds(0) == 0


# ── Drainer send_one ───────────────────────────────────────────────────

from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def drainer_db(tmp_path):
    """A test DB with Base.metadata.create_all applied."""
    from models import Base

    db_path = str(tmp_path / "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def get_db():
        async with factory() as session:
            yield session

    yield factory, get_db

    await engine.dispose()


@pytest_asyncio.fixture
async def pending_row(drainer_db):
    """Insert one pending row with status=completed and return its id."""
    from models import PendingCallbackDB
    factory, _ = drainer_db
    async with factory() as session:
        row = PendingCallbackDB(
            job_id=1, status="completed",
            next_attempt_at=datetime.now(timezone.utc),
            attempt_count=0,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


@pytest.mark.asyncio
async def test_send_one_marks_delivered_on_2xx(drainer_db, pending_row):
    from callback_drainer import TranscodeCallbackDrainer
    from models import PendingCallbackDB

    factory, get_db = drainer_db

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(200)

    drainer = TranscodeCallbackDrainer(
        get_db=get_db,
        callback_url="https://arm.example/callback",
        http_client_factory=lambda: mock_client,
    )

    await drainer.send_one(pending_row)

    async with factory() as session:
        result = await session.execute(
            select(PendingCallbackDB).where(PendingCallbackDB.id == pending_row)
        )
        row = result.scalar_one()
        assert row.delivered_at is not None
        assert row.permanent_failure_at is None


@pytest.mark.asyncio
async def test_send_one_marks_permanent_failure_on_400(drainer_db, pending_row):
    from callback_drainer import TranscodeCallbackDrainer
    from models import PendingCallbackDB

    factory, get_db = drainer_db

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(400, text="bad payload")

    drainer = TranscodeCallbackDrainer(
        get_db=get_db,
        callback_url="https://arm.example/callback",
        http_client_factory=lambda: mock_client,
    )

    await drainer.send_one(pending_row)

    async with factory() as session:
        result = await session.execute(
            select(PendingCallbackDB).where(PendingCallbackDB.id == pending_row)
        )
        row = result.scalar_one()
        assert row.delivered_at is None
        assert row.permanent_failure_at is not None
        assert "400" in row.last_error


@pytest.mark.asyncio
async def test_send_one_retriable_on_503(drainer_db, pending_row):
    from callback_drainer import TranscodeCallbackDrainer
    from models import PendingCallbackDB

    factory, get_db = drainer_db

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(503)

    before = datetime.now(timezone.utc)
    drainer = TranscodeCallbackDrainer(
        get_db=get_db,
        callback_url="https://arm.example/callback",
        http_client_factory=lambda: mock_client,
    )

    await drainer.send_one(pending_row)

    async with factory() as session:
        result = await session.execute(
            select(PendingCallbackDB).where(PendingCallbackDB.id == pending_row)
        )
        row = result.scalar_one()
        assert row.delivered_at is None
        assert row.permanent_failure_at is None
        assert row.attempt_count == 1
        # Next attempt should be at least 5s after now (first backoff).
        # SQLite stores naive datetimes; strip tzinfo from before for comparison.
        before_naive = before.replace(tzinfo=None)
        next_at = row.next_attempt_at.replace(tzinfo=None) if row.next_attempt_at.tzinfo else row.next_attempt_at
        assert next_at >= before_naive + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_send_one_retriable_on_network_error(drainer_db, pending_row):
    from callback_drainer import TranscodeCallbackDrainer
    from models import PendingCallbackDB

    factory, get_db = drainer_db

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.ConnectError("refused")

    drainer = TranscodeCallbackDrainer(
        get_db=get_db,
        callback_url="https://arm.example/callback",
        http_client_factory=lambda: mock_client,
    )

    await drainer.send_one(pending_row)

    async with factory() as session:
        result = await session.execute(
            select(PendingCallbackDB).where(PendingCallbackDB.id == pending_row)
        )
        row = result.scalar_one()
        assert row.delivered_at is None
        assert row.permanent_failure_at is None
        assert row.attempt_count == 1
        assert row.last_error is not None
        assert "refused" in row.last_error
