"""
NVIDIA NVENC scheme stub.

Full preset definitions are implemented in a later task.
"""

from presets import Encoder, Preset, Scheme

_TIERS: dict = {
    "dvd":    {"handbrake_preset": "H.265 NVENC 1080p"},
    "bluray": {"handbrake_preset": "H.265 NVENC 1080p"},
    "uhd":    {"handbrake_preset": "H.265 NVENC 2160p 4K"},
}

SCHEME = Scheme(
    slug="nvidia",
    name="NVIDIA NVENC",
    supported_encoders=[
        Encoder(slug="nvenc_h265", name="NVENC H.265"),
        Encoder(slug="nvenc_h264", name="NVENC H.264"),
    ],
    supported_audio_encoders=["copy", "aac", "ac3", "eac3", "flac", "mp3"],
    supported_subtitle_modes=["all", "none", "first"],
    advanced_fields={},
    built_in_presets=[
        Preset(
            slug="balanced",
            name="Balanced",
            scheme="nvidia",
            description="Good balance of quality and speed (NVENC H.265)",
            shared={"video_encoder": "nvenc_h265", "video_quality": 22, "audio_encoder": "copy"},
            tiers=_TIERS,
        ),
    ],
)
