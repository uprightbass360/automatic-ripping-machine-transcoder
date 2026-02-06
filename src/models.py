"""
Data models for ARM Transcoder
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import declarative_base

from constants import (
    MAX_TITLE_LENGTH,
    MAX_BODY_LENGTH,
    MAX_PATH_LENGTH,
    MAX_JOB_ID_LENGTH,
)

Base = declarative_base()


class JobStatus(str, Enum):
    """Transcode job status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TranscodeJobDB(Base):
    """Database model for transcode jobs."""
    __tablename__ = "transcode_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    source_path = Column(String(1000), nullable=False)
    output_path = Column(String(1000), nullable=True)
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, nullable=False)
    progress = Column(Float, default=0.0)
    arm_job_id = Column(String(50), nullable=True)  # Reference to ARM job
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Metadata from source
    video_type = Column(String(50), nullable=True)  # movie, tv, unknown
    year = Column(String(10), nullable=True)
    total_tracks = Column(Integer, default=0)
    main_feature_file = Column(String(500), nullable=True)


class WebhookPayload(BaseModel):
    """Webhook payload from ARM with validation."""

    title: str = Field(..., max_length=MAX_TITLE_LENGTH)
    body: Optional[str] = Field(None, max_length=MAX_BODY_LENGTH)
    path: Optional[str] = Field(None, max_length=MAX_PATH_LENGTH)
    job_id: Optional[str] = Field(None, max_length=MAX_JOB_ID_LENGTH)
    status: Optional[str] = Field(None, max_length=50)
    type: Optional[str] = Field(None, max_length=50)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """Validate title field."""
        if not v or not v.strip():
            raise ValueError("Title cannot be empty")

        # Remove control characters
        cleaned = "".join(char for char in v if ord(char) >= 32)
        return cleaned.strip()

    @field_validator("body")
    @classmethod
    def validate_body(cls, v: Optional[str]) -> Optional[str]:
        """Validate body field."""
        if v is None:
            return v

        # Remove control characters except newlines and tabs
        cleaned = "".join(
            char for char in v if char in "\n\t" or ord(char) >= 32
        )
        return cleaned.strip()

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: Optional[str]) -> Optional[str]:
        """Validate path field."""
        if v is None:
            return v

        # Basic path validation (actual validation happens later with PathValidator)
        # Remove null bytes and control characters
        cleaned = v.replace("\x00", "")
        cleaned = "".join(char for char in cleaned if ord(char) >= 32)

        return cleaned.strip()

    @field_validator("job_id")
    @classmethod
    def validate_job_id(cls, v: Optional[str]) -> Optional[str]:
        """Validate job_id field."""
        if v is None:
            return v

        # Allow only alphanumeric, hyphens, and underscores
        import re
        if not re.match(r'^[a-zA-Z0-9\-_]+$', v):
            raise ValueError("Job ID contains invalid characters")

        return v


class TranscodeJob(BaseModel):
    """Transcode job for queue."""
    id: Optional[int] = None
    title: str
    source_path: str
    arm_job_id: Optional[str] = None

    class Config:
        from_attributes = True
