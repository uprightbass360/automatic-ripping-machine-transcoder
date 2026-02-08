"""
Configuration settings for ARM Transcoder
"""

from pydantic_settings import BaseSettings
from pydantic import Field, field_validator

from constants import (
    VALID_VIDEO_ENCODERS,
    VALID_AUDIO_ENCODERS,
    VALID_SUBTITLE_MODES,
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Paths
    raw_path: str = Field("/data/raw", description="Path to raw MKV files from ARM")
    completed_path: str = Field("/data/completed", description="Path for completed transcodes")
    work_path: str = Field("/data/work", description="Temporary working directory")
    db_path: str = Field("/data/db/transcoder.db", description="SQLite database path")
    preset_path: str = Field("/config/presets", description="HandBrake presets directory")

    # Authentication
    require_api_auth: bool = Field(
        False,
        description="Require API key authentication for all endpoints"
    )
    api_keys: str = Field(
        "",
        description="Comma-separated API keys. Format: 'key1,key2' or 'admin:key1,readonly:key2'"
    )
    webhook_secret: str = Field(
        "",
        description="Optional secret for webhook authentication (X-Webhook-Secret header)"
    )

    # Transcoding
    handbrake_preset: str = Field(
        "NVENC H.265 1080p",
        description="HandBrake preset name to use"
    )
    handbrake_preset_4k: str = Field(
        "H.265 NVENC 2160p 4K",
        description="HandBrake preset for 4K content"
    )
    handbrake_preset_file: str = Field(
        "",
        description="Path to custom preset JSON file (overrides preset name)"
    )
    video_encoder: str = Field(
        "nvenc_h265",
        description=f"Video encoder. Valid: {', '.join(VALID_VIDEO_ENCODERS)}"
    )
    video_quality: int = Field(
        22,
        ge=0,
        le=51,
        description="Video quality (CRF-like, lower is better, 0-51)"
    )
    audio_encoder: str = Field(
        "copy",
        description=f"Audio encoder. Valid: {', '.join(VALID_AUDIO_ENCODERS)}"
    )
    subtitle_mode: str = Field(
        "all",
        description=f"Subtitle handling. Valid: {', '.join(VALID_SUBTITLE_MODES)}"
    )

    # File handling
    delete_source: bool = Field(
        True,
        description="Delete source files after successful transcode"
    )
    output_extension: str = Field("mkv", description="Output file extension")

    # Organization
    movies_subdir: str = Field("movies", description="Subdirectory for movies")
    tv_subdir: str = Field("tv", description="Subdirectory for TV shows")
    audio_subdir: str = Field("audio", description="Subdirectory for audio")

    # Concurrency
    max_concurrent: int = Field(
        1,
        ge=1,
        le=10,
        description="Max concurrent transcodes (1 recommended for single GPU)"
    )
    stabilize_seconds: int = Field(
        60,
        ge=10,
        le=600,
        description="Seconds to wait for source folder to stabilize"
    )

    # Disk space
    minimum_free_space_gb: float = Field(
        10.0,
        ge=1.0,
        description="Minimum free disk space required (GB)"
    )

    # Retry configuration
    max_retry_count: int = Field(
        3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed jobs"
    )

    # Logging
    log_level: str = Field("INFO", description="Logging level")

    @field_validator("video_encoder")
    @classmethod
    def validate_video_encoder(cls, v: str) -> str:
        """Validate video encoder."""
        if v not in VALID_VIDEO_ENCODERS:
            raise ValueError(
                f"Invalid video encoder: {v}. "
                f"Valid options: {', '.join(VALID_VIDEO_ENCODERS)}"
            )
        return v

    @field_validator("audio_encoder")
    @classmethod
    def validate_audio_encoder(cls, v: str) -> str:
        """Validate audio encoder."""
        if v not in VALID_AUDIO_ENCODERS:
            raise ValueError(
                f"Invalid audio encoder: {v}. "
                f"Valid options: {', '.join(VALID_AUDIO_ENCODERS)}"
            )
        return v

    @field_validator("subtitle_mode")
    @classmethod
    def validate_subtitle_mode(cls, v: str) -> str:
        """Validate subtitle mode."""
        if v not in VALID_SUBTITLE_MODES:
            raise ValueError(
                f"Invalid subtitle mode: {v}. "
                f"Valid options: {', '.join(VALID_SUBTITLE_MODES)}"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. "
                f"Valid options: {', '.join(valid_levels)}"
            )
        return v_upper

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = Settings()
