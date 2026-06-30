"""Shared test fixtures and lightweight stubs (no real media tools needed)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pytest

# Make the project importable when running pytest from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vidcomp.core.media import MediaTools  # noqa: E402
from vidcomp.core.methods.base import MethodContext  # noqa: E402
from vidcomp.core.models import MediaInfo, VideoFile  # noqa: E402


@dataclass
class StubTools:
    """A MediaTools stand-in that pretends the tools are present."""

    _ffmpeg: bool = True
    _ffprobe: bool = True
    _fpcalc: bool = True
    _vmaf: bool = True

    @property
    def has_ffmpeg(self) -> bool:
        return self._ffmpeg

    @property
    def has_ffprobe(self) -> bool:
        return self._ffprobe

    @property
    def has_fpcalc(self) -> bool:
        return self._fpcalc

    def has_vmaf(self) -> bool:
        return self._vmaf

    def probe(self, path: str):  # pragma: no cover - not used when info preset
        return MediaInfo()


def make_video(path: str, size: int, mtime: float = 1000.0, info: MediaInfo | None = None) -> VideoFile:
    vf = VideoFile(path=path, size=size, mtime=mtime, ctime=mtime)
    vf.info = info
    return vf


@pytest.fixture
def ctx(tmp_path) -> MethodContext:
    from vidcomp.config import ScanOptions

    return MethodContext(
        tools=StubTools(),
        options=ScanOptions(),
        temp_dir=str(tmp_path),
    )


@pytest.fixture
def real_tools() -> MediaTools:
    return MediaTools()
