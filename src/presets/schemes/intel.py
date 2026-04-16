"""
Intel QSV scheme stub.

Full preset definitions are implemented in a later task.
"""

from presets import Encoder, Preset, Scheme

_TIERS: dict = {
    "dvd":    {"handbrake_preset": "H.265 QSV 1080p"},
    "bluray": {"handbrake_preset": "H.265 QSV 1080p"},
    "uhd":    {"handbrake_preset": "H.265 QSV 2160p 4K"},
}

SCHEME = Scheme(
    slug="intel",
    name="Intel QSV",
    supported_encoders=[
        Encoder(slug="qsv_h265", name="QSV H.265"),
        Encoder(slug="qsv_h264", name="QSV H.264"),
    ],
    supported_audio_encoders=["copy", "aac", "ac3", "eac3", "flac", "mp3"],
    supported_subtitle_modes=["all", "none", "first"],
    advanced_fields=[],
    built_in_presets=[
        Preset(
            slug="balanced",
            name="Balanced",
            scheme="intel",
            description="Good balance of quality and speed (Intel QSV H.265)",
            shared={"video_encoder": "qsv_h265", "video_quality": 22, "audio_encoder": "copy"},
            tiers=_TIERS,
        ),
    ],
)
