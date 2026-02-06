"""
Configuration settings for ARM Transcoder
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Paths
    raw_path: str = Field("/data/raw", description="Path to raw MKV files from ARM")
    completed_path: str = Field("/data/completed", description="Path for completed transcodes")
    work_path: str = Field("/data/work", description="Temporary working directory")
    db_path: str = Field("/data/db/transcoder.db", description="SQLite database path")
    preset_path: str = Field("/config/presets", description="HandBrake presets directory")

    # Webhook
    webhook_secret: str = Field("", description="Optional secret for webhook authentication")

    # Transcoding
    handbrake_preset: str = Field(
        "NVENC H.265 1080p",
        description="HandBrake preset name to use"
    )
    handbrake_preset_file: str = Field(
        "",
        description="Path to custom preset JSON file (overrides preset name)"
    )
    video_encoder: str = Field("nvenc_h265", description="Video encoder (nvenc_h265, nvenc_h264, etc)")
    video_quality: int = Field(22, description="Video quality (CRF-like, lower is better)")
    audio_encoder: str = Field("copy", description="Audio encoder (copy, aac, ac3, etc)")
    subtitle_mode: str = Field("all", description="Subtitle handling: all, none, first")

    # File handling
    delete_source: bool = Field(True, description="Delete source files after successful transcode")
    output_extension: str = Field("mkv", description="Output file extension")

    # Organization
    movies_subdir: str = Field("movies", description="Subdirectory for movies")
    tv_subdir: str = Field("tv", description="Subdirectory for TV shows")

    # Concurrency
    max_concurrent: int = Field(1, description="Max concurrent transcodes (1 for GPU)")
    stabilize_seconds: int = Field(60, description="Seconds to wait for source folder to stabilize")

    # Logging
    log_level: str = Field("INFO", description="Logging level")

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = Settings()
