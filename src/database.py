"""
Database setup and session management
"""

import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from config import settings
from models import Base

# Ensure database directory exists
os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)

# Create async engine
engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.db_path}",
    echo=False,
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_db():
    """Get database session context manager."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
