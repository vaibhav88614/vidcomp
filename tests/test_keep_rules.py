"""Tests for keep-rule strategies."""

from __future__ import annotations

from vidcomp.config import (
    KEEP_LARGEST,
    KEEP_MANUAL,
    KEEP_NEWEST,
    KEEP_OLDEST,
)
from vidcomp.core.keep_rules import apply_keep_rule
from vidcomp.core.models import DuplicateGroup, VideoFile


def _g(*files: VideoFile) -> DuplicateGroup:
    return DuplicateGroup(group_id=1, files=list(files))


def _vf(name: str, size: int, mtime: float) -> VideoFile:
    return VideoFile(path=f"C:/x/{name}", size=size, mtime=mtime, ctime=mtime)


def test_keep_largest():
    a = _vf("a", size=100, mtime=10.0)
    b = _vf("b", size=200, mtime=10.0)
    c = _vf("c", size=150, mtime=10.0)
    g = _g(a, b, c)
    kept = apply_keep_rule(g, KEEP_LARGEST, ctx=None)
    assert kept.path == b.path
    assert g.keeper_path == b.path


def test_keep_newest():
    a = _vf("a", size=100, mtime=10.0)
    b = _vf("b", size=100, mtime=20.0)
    c = _vf("c", size=100, mtime=15.0)
    g = _g(a, b, c)
    kept = apply_keep_rule(g, KEEP_NEWEST, ctx=None)
    assert kept.path == b.path


def test_keep_oldest():
    a = _vf("a", size=100, mtime=10.0)
    b = _vf("b", size=100, mtime=20.0)
    g = _g(a, b)
    kept = apply_keep_rule(g, KEEP_OLDEST, ctx=None)
    assert kept.path == a.path


def test_keep_manual_returns_none():
    a = _vf("a", size=100, mtime=10.0)
    b = _vf("b", size=200, mtime=20.0)
    g = _g(a, b)
    kept = apply_keep_rule(g, KEEP_MANUAL, ctx=None)
    assert kept is None
    assert g.keeper_path is None


def test_reclaimable_bytes_after_keep():
    a = _vf("a", size=100, mtime=10.0)
    b = _vf("b", size=200, mtime=10.0)
    c = _vf("c", size=150, mtime=10.0)
    g = _g(a, b, c)
    apply_keep_rule(g, KEEP_LARGEST, ctx=None)  # keeps b (200)
    assert g.reclaimable_bytes() == 100 + 150
