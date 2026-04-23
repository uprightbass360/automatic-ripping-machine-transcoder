"""Durable queue drainer for ARM-callback POSTs.

Replaces the inline 3-retry pattern in transcoder._notify_arm_callback.
_notify_arm_callback enqueues a PendingCallbackDB row; this module's
TranscodeCallbackDrainer loops over the table, POSTs to arm-neu, and
updates row state based on the response.

See docs/superpowers/specs/2026-04-23-callback-retry-refactor-design.md
for the spec.
"""
import httpx


# HTTP codes where arm-neu's response tells us the callback will never
# succeed. Do NOT retry. The row stays in the table with
# permanent_failure_at set so an operator can audit.
_PERMANENT_HTTP_CODES = frozenset({400, 401, 403, 404, 410, 422})


def is_permanent_error(exc_or_response) -> bool:
    """Classify a send outcome as permanent (no retry) vs retriable.

    Permanent: explicit 4xx codes in _PERMANENT_HTTP_CODES.
    Retriable: everything else - 408, 429, 5xx, network errors, timeouts.
    Not-permanent for 2xx either; callers short-circuit on success
    before reaching this classifier.
    """
    if isinstance(exc_or_response, httpx.Response):
        return exc_or_response.status_code in _PERMANENT_HTTP_CODES
    # httpx exceptions (ConnectError, ReadTimeout, etc.) are all retriable.
    return False


_BASE_DELAY_SECONDS = 5
_MAX_DELAY_SECONDS = 1800  # 30 minutes


def backoff_seconds(attempt_count: int) -> int:
    """Return the delay before attempt #(attempt_count + 1).

    Schedule: 5, 10, 20, 40, 80, 160, 320, 640, 1280, 1800, 1800, ...
    First retry after 5s; doubles per attempt; capped at 30 minutes.
    attempt_count=0 returns 0 (send immediately).
    """
    if attempt_count <= 0:
        return 0
    return min(_BASE_DELAY_SECONDS * (2 ** (attempt_count - 1)), _MAX_DELAY_SECONDS)
