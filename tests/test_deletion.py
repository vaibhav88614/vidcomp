"""Tests for deletion safety (survivor rule) and quarantine moves."""

from __future__ import annotations

import os

import pytest

from vidcomp.core.deletion import (
    SurvivorViolation,
    delete_path,
    delete_paths,
    enforce_survivors,
)
from vidcomp.core.models import DeleteMode, DuplicateGroup

from .conftest import make_video


def _group(paths):
    return DuplicateGroup(files=[make_video(p, 10) for p in paths])


def test_enforce_survivors_blocks_full_group_deletion():
    g = _group(["a.mp4", "b.mp4"])
    with pytest.raises(SurvivorViolation):
        enforce_survivors(["a.mp4", "b.mp4"], [g])


def test_enforce_survivors_allows_partial():
    g = _group(["a.mp4", "b.mp4"])
    cleared = enforce_survivors(["a.mp4"], [g])
    assert cleared == ["a.mp4"]


def test_quarantine_move(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"data")
    quarantine = tmp_path / "q"
    res = delete_path(str(src), DeleteMode.QUARANTINE, str(quarantine))
    assert res.success
    assert not src.exists()
    assert res.destination and os.path.isfile(res.destination)


def test_permanent_delete(tmp_path):
    src = tmp_path / "video.mp4"
    src.write_bytes(b"data")
    res = delete_path(str(src), DeleteMode.PERMANENT)
    assert res.success
    assert not src.exists()


def test_delete_missing_file_reports_failure(tmp_path):
    res = delete_path(str(tmp_path / "nope.mp4"), DeleteMode.PERMANENT)
    assert not res.success
    assert res.error


def test_delete_paths_enforces_groups(tmp_path):
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    g = _group([str(a), str(b)])
    with pytest.raises(SurvivorViolation):
        delete_paths([str(a), str(b)], DeleteMode.PERMANENT, groups=[g])
    # Both files still present because the unsafe batch was rejected.
    assert a.exists() and b.exists()
