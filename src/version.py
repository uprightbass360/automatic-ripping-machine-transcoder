"""API version constant for the cross-service ARM handshake.

Bumped when the webhook payload shape (or other cross-service contract)
changes in a backwards-incompatible way.

  v1 - pre-preset, flat encoding keys (video_encoder, handbrake_preset*, ...)
  v2 - preset-based shape (preset_slug + overrides dict)
"""

API_VERSION = "2"

# Versions that the current transcoder accepts. During release N/N+1,
# missing header is also accepted for rolling-upgrade compatibility.
# Release N+2 will drop missing-header acceptance.
ACCEPTED_VERSIONS = frozenset({"2"})
ACCEPT_MISSING_VERSION_HEADER = True  # flip to False in release N+2
