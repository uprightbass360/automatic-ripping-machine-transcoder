"""Unit tests for callback drainer components."""
import httpx
import pytest


# ── is_permanent_error ─────────────────────────────────────────────────

@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 422])
def test_permanent_error_for_terminal_4xx_codes(code):
    from callback_drainer import is_permanent_error
    response = httpx.Response(code)
    assert is_permanent_error(response) is True


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_retriable_for_non_terminal_error_codes(code):
    from callback_drainer import is_permanent_error
    response = httpx.Response(code)
    assert is_permanent_error(response) is False


@pytest.mark.parametrize("code", [200, 201, 202, 204])
def test_not_permanent_for_success_codes(code):
    """Success isn't classified as permanent failure; the caller checks
    status_code < 300 separately before reaching this function."""
    from callback_drainer import is_permanent_error
    response = httpx.Response(code)
    assert is_permanent_error(response) is False


def test_network_exception_is_retriable():
    from callback_drainer import is_permanent_error
    exc = httpx.ConnectError("refused")
    assert is_permanent_error(exc) is False


def test_timeout_exception_is_retriable():
    from callback_drainer import is_permanent_error
    exc = httpx.ReadTimeout("timed out")
    assert is_permanent_error(exc) is False
