"""Tests for the union-find grouping in :mod:`vidcomp.core.grouping`."""

from __future__ import annotations

from pathlib import Path

from vidcomp.core.grouping import build_groups
from vidcomp.core.models import PairResult, VideoFile


def _vf(name: str, size: int = 1024, mtime: float = 1700000000.0) -> VideoFile:
    return VideoFile(path=f"C:/test/{name}", size=size, mtime=mtime, ctime=mtime)


def test_build_groups_simple_pair():
    a = _vf("a.mp4")
    b = _vf("b.mp4")
    pair = PairResult(path_a=a.path, path_b=b.path, matched=True)
    groups = build_groups([a, b], [pair])
    assert len(groups) == 1
    assert {f.path for f in groups[0].files} == {a.path, b.path}


def test_build_groups_singleton_dropped():
    a = _vf("a.mp4")
    groups = build_groups([a], [])
    assert groups == []


def test_build_groups_transitive_closure():
    a = _vf("a.mp4")
    b = _vf("b.mp4")
    c = _vf("c.mp4")
    pairs = [
        PairResult(a.path, b.path, matched=True),
        PairResult(b.path, c.path, matched=True),
    ]
    groups = build_groups([a, b, c], pairs)
    assert len(groups) == 1
    assert {f.path for f in groups[0].files} == {a.path, b.path, c.path}


def test_build_groups_multiple_groups():
    a, b, c, d = (_vf(n) for n in ("a", "b", "c", "d"))
    pairs = [
        PairResult(a.path, b.path, matched=True),
        PairResult(c.path, d.path, matched=True),
    ]
    groups = build_groups([a, b, c, d], pairs)
    assert len(groups) == 2
    paths = sorted([sorted(f.path for f in g.files) for g in groups])
    assert paths == [sorted([a.path, b.path]), sorted([c.path, d.path])]


def test_build_groups_assigns_increasing_ids():
    files = [_vf(n) for n in ("a", "b", "c", "d")]
    pairs = [
        PairResult(files[0].path, files[1].path, matched=True),
        PairResult(files[2].path, files[3].path, matched=True),
    ]
    groups = build_groups(files, pairs)
    assert sorted(g.group_id for g in groups) == [1, 2]


def test_build_groups_includes_pair_scores():
    a = _vf("a")
    b = _vf("b")
    pr = PairResult(a.path, b.path, matched=True)
    groups = build_groups([a, b], [pr])
    g = groups[0]
    key = tuple(sorted([a.path, b.path]))
    assert key in g.pair_scores
