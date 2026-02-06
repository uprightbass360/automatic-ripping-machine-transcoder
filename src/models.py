"""
Data models for ARM Transcoder
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class JobStatus(str, Enum):
    """Transcode job status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Metadata from source
    video_type = Column(String(50), nullable=True)  # movie, tv, unknown
    year = Column(String(10), nullable=True)
    total_tracks = Column(Integer, default=0)
    main_feature_file = Column(String(500), nullable=True)


class WebhookPayload(BaseModel):
    """Webhook payload from ARM."""
    title: str
    body: Optional[str] = None
    path: Optional[str] = None
    job_id: Optional[str] = None
    status: Optional[str] = None
    type: Optional[str] = None  # info, success, error


class TranscodeJob(BaseModel):
    """Transcode job for queue."""
    id: Optional[int] = None
    title: str
    source_path: str
    arm_job_id: Optional[str] = None

    class Config:
        from_attributes = True
