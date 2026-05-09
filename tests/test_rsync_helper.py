"""Tests for arm-transcoder's async rsync wrapper.

Same conformance suite as arm-neu's sync helper, run through an
AsyncAdapter that bridges asyncio.run() into a sync return value."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from arm_contracts import RsyncProgressEvent

from tests._rsync_conformance import (
    assert_partial_transfer_raises,
    assert_remove_source_cleanup,
    assert_streams_progress,
)


class AsyncAdapter:
    """Wraps run_rsync_async behind a sync return so the conformance suite
    works without knowing the helper is async. Uses asyncio.run per call so
    each test runs in a fresh event loop."""

    def run_to_completion(
        self,
        src: str,
        dst: str,
        *,
        remove_source: bool = False,
    ) -> list[RsyncProgressEvent]:
        from rsync_helper import run_rsync_async
        events: list[RsyncProgressEvent] = []
        asyncio.run(
            run_rsync_async(src, dst, on_progress=events.append, remove_source=remove_source)
        )
        return events


@pytest.fixture
def adapter():
    return AsyncAdapter()


def test_conformance_streams_progress(adapter, tmp_path):
    assert_streams_progress(adapter, tmp_path)


def test_conformance_partial_transfer_raises(adapter, tmp_path):
    assert_partial_transfer_raises(adapter, tmp_path)


def test_conformance_remove_source_cleanup(adapter, tmp_path):
    assert_remove_source_cleanup(adapter, tmp_path)
