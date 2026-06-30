"""Tests for keep-rule selection and duplicate auto-selection safety."""

from __future__ import annotations

from vidcomp.core.keep_rules import apply_keep_rule, auto_select_duplicates, pick_keeper
from vidcomp.core.models import DuplicateGroup, KeepRule, MediaInfo

from .conftest import make_video


def _group():
    small = make_video("small.mp4", 100, mtime=1000.0,
                       info=MediaInfo(duration=60.0, width=640, height=480, ok=True))
    big = make_video("big.mp4", 500, mtime=2000.0,
                     info=MediaInfo(duration=90.0, width=1920, height=1080, ok=True))
    mid = make_video("mid.mp4", 300, mtime=1500.0,
                     info=MediaInfo(duration=120.0, width=1280, height=720, ok=True))
    return DuplicateGroup(files=[small, big, mid])


def test_keep_highest_resolution():
    assert pick_keeper(_group(), KeepRule.HIGHEST_RESOLUTION).name == "big.mp4"


def test_keep_largest_size():
    assert pick_keeper(_group(), KeepRule.LARGEST_SIZE).name == "big.mp4"


def test_keep_longest_duration():
    assert pick_keeper(_group(), KeepRule.LONGEST_DURATION).name == "mid.mp4"


def test_keep_newest_and_oldest():
    assert pick_keeper(_group(), KeepRule.NEWEST).name == "big.mp4"
    assert pick_keeper(_group(), KeepRule.OLDEST).name == "small.mp4"


def test_auto_select_preserves_keeper():
    g = _group()
    selected = auto_select_duplicates(g, KeepRule.LARGEST_SIZE)
    assert "big.mp4" not in [p.split("/")[-1].split("\\")[-1] for p in selected]
    assert len(selected) == len(g.files) - 1


def test_apply_keep_rule_sets_path():
    g = _group()
    apply_keep_rule([g], KeepRule.HIGHEST_RESOLUTION)
    assert g.keep_path == "big.mp4"
    # Reclaimable excludes the kept file.
    assert g.reclaimable == 100 + 300
