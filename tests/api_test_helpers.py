"""Shared helpers for HTTP-level tests against the transcoder app."""

from httpx import ASGITransport, AsyncClient


def versioned_test_client(app, base_url: str = "https://test") -> AsyncClient:
    """Build an httpx AsyncClient with X-Api-Version: 2 on every request.

    Tests that target webhook behaviour (not the version-handshake) should
    default the header so they aren't rejected by the release-N+2 guard.
    Handshake-specific tests live in test_version_handshake.py.
    """
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url=base_url,
        headers={"X-Api-Version": "2"},
    )
