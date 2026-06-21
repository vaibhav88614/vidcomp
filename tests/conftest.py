"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Iterator

import pytest

# Make the package importable when running ``pytest`` from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def cache(tmp_path: Path):
    from vidcomp.core.cache import Cache

    c = Cache(tmp_path / "test_cache.sqlite")
    yield c
    c.close()


@pytest.fixture
def cancel_event() -> threading.Event:
    return threading.Event()


@pytest.fixture
def app_config():
    from vidcomp.config import AppConfig

    return AppConfig()


@pytest.fixture
def context(cache, cancel_event, app_config):
    from vidcomp.core.methods.base import MethodContext

    return MethodContext(cache=cache, cancel_event=cancel_event, config=app_config)


def make_dummy_video_file(path: Path, content: bytes, mtime: float | None = None):
    """Write *content* to *path* and return a :class:`VideoFile` for it."""
    from vidcomp.core.models import VideoFile

    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    st = path.stat()
    return VideoFile(
        path=str(path),
        size=st.st_size,
        mtime=st.st_mtime,
        ctime=st.st_ctime,
    )
