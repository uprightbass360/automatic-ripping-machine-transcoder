"""
AMD VAAPI/AMF scheme stub.

Full preset definitions are implemented in a later task.
"""

from presets import Encoder, Preset, Scheme

_TIERS: dict = {
    "dvd":    {"handbrake_preset": "H.265 VCN 1080p"},
    "bluray": {"handbrake_preset": "H.265 VCN 1080p"},
    "uhd":    {"handbrake_preset": "H.265 VCN 2160p 4K"},
}

SCHEME = Scheme(
    slug="amd",
    name="AMD VAAPI/AMF",
    supported_encoders=[
        Encoder(slug="vaapi_h265", name="VAAPI H.265"),
        Encoder(slug="vaapi_h264", name="VAAPI H.264"),
    ],
    supported_audio_encoders=["copy", "aac", "ac3", "eac3", "flac", "mp3"],
    supported_subtitle_modes=["all", "none", "first"],
    advanced_fields={},
    built_in_presets=[
        Preset(
            slug="balanced",
            name="Balanced",
            scheme="amd",
            description="Good balance of quality and speed (AMD VAAPI H.265)",
            shared={"video_encoder": "vaapi_h265", "video_quality": 22, "audio_encoder": "copy"},
            tiers=_TIERS,
        ),
    ],
)
