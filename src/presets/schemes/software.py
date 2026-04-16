"""
Software (CPU) scheme stub.

Full preset definitions are implemented in a later task.
"""

from presets import Encoder, Preset, Scheme

_TIERS: dict = {
    "dvd":    {"handbrake_preset": "H.265 MKV 720p30"},
    "bluray": {"handbrake_preset": "H.265 MKV 1080p30"},
    "uhd":    {"handbrake_preset": "H.265 MKV 2160p60 4K"},
}

SCHEME = Scheme(
    slug="software",
    name="Software (CPU)",
    supported_encoders=[
        Encoder(slug="x265", name="Software x265"),
        Encoder(slug="x264", name="Software x264"),
    ],
    supported_audio_encoders=["copy", "aac", "ac3", "eac3", "flac", "mp3"],
    supported_subtitle_modes=["all", "none", "first"],
    advanced_fields=[],
    built_in_presets=[
        Preset(
            slug="balanced",
            name="Balanced",
            scheme="software",
            description="Good balance of quality and speed (CPU x265)",
            shared={"video_encoder": "x265", "video_quality": 22, "audio_encoder": "copy"},
            tiers=_TIERS,
        ),
    ],
)
