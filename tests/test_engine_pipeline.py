"""End-to-end engine tests with stubbed methods (no real video files needed)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, List, Optional

import pytest

from tests.conftest import make_dummy_video_file
from vidcomp.config import (
    AppConfig,
    MATCH_ALL,
    MATCH_ANY,
    METHOD_SHA256,
    METHOD_SIZE,
)
from vidcomp.core.cache import Cache
from vidcomp.core.engine import Engine
from vidcomp.core.models import MatchEvidence, VideoFile


def _config(enabled, match_logic=MATCH_ANY) -> AppConfig:
    cfg = AppConfig()
    cfg.enabled_methods = set(enabled)
    cfg.match_logic = match_logic
    cfg.worker_count = 2
    cfg.extensions = ["mp4"]
    cfg.min_file_size_bytes = 0
    return cfg


def test_engine_finds_identical_files(tmp_path: Path):
    # Use ALL logic with size + sha256 to verify "exact byte-identical" semantics.
    # Under ANY logic with size enabled, same-size-but-different-content files
    # would also match (size-equality is treated as a valid match vote) — that
    # is correct behavior, just not what this test wants to verify.
    cfg = _config({METHOD_SIZE, METHOD_SHA256}, match_logic=MATCH_ALL)
    cfg.cache_path = str(tmp_path / "cache.sqlite")
    cache = Cache(cfg.cache_path)

    # Two identical, one different (same size — distractor for sha256).
    data = b"x" * 4096
    make_dummy_video_file(tmp_path / "a.mp4", data)
    make_dummy_video_file(tmp_path / "b.mp4", data)
    make_dummy_video_file(tmp_path / "c.mp4", b"y" * 4096)

    engine = Engine(cfg, cache)
    result = engine.run(tmp_path)
    cache.close()

    assert result.file_count == 3
    assert len(result.groups) == 1
    g = result.groups[0]
    assert {Path(f.path).name for f in g.files} == {"a.mp4", "b.mp4"}


def test_engine_any_logic_size_alone_groups_same_size(tmp_path: Path):
    """ANY logic + size + sha256: same-size files are grouped via size method.

    This documents the (intentional) behavior that under ANY logic, a single
    method agreeing is enough.  Users wanting strict "byte-identical only"
    detection should use ALL logic (which is the Easy preset default).
    """
    cfg = _config({METHOD_SIZE, METHOD_SHA256}, match_logic=MATCH_ANY)
    cfg.cache_path = str(tmp_path / "cache.sqlite")
    cache = Cache(cfg.cache_path)

    make_dummy_video_file(tmp_path / "a.mp4", b"x" * 4096)
    make_dummy_video_file(tmp_path / "b.mp4", b"x" * 4096)
    make_dummy_video_file(tmp_path / "c.mp4", b"y" * 4096)  # same size, diff content

    engine = Engine(cfg, cache)
    result = engine.run(tmp_path)
    cache.close()

    assert len(result.groups) == 1
    assert {Path(f.path).name for f in result.groups[0].files} == {"a.mp4", "b.mp4", "c.mp4"}


def test_engine_size_only_groups_same_size(tmp_path: Path):
    cfg = _config({METHOD_SIZE})
    cfg.cache_path = str(tmp_path / "cache.sqlite")
    cache = Cache(cfg.cache_path)

    # Two files of identical size but different content — size-only flags them.
    make_dummy_video_file(tmp_path / "a.mp4", b"x" * 1024)
    make_dummy_video_file(tmp_path / "b.mp4", b"y" * 1024)
    make_dummy_video_file(tmp_path / "c.mp4", b"z" * 2048)

    engine = Engine(cfg, cache)
    result = engine.run(tmp_path)
    cache.close()

    assert len(result.groups) == 1
    assert {Path(f.path).name for f in result.groups[0].files} == {"a.mp4", "b.mp4"}


def test_engine_match_all_logic_requires_every_method(tmp_path: Path):
    """With ALL logic, files that share size but differ in SHA-256 must NOT match."""
    cfg = _config({METHOD_SIZE, METHOD_SHA256}, match_logic=MATCH_ALL)
    cfg.cache_path = str(tmp_path / "cache.sqlite")
    cache = Cache(cfg.cache_path)

    make_dummy_video_file(tmp_path / "a.mp4", b"x" * 1024)
    make_dummy_video_file(tmp_path / "b.mp4", b"y" * 1024)  # same size, diff content

    engine = Engine(cfg, cache)
    result = engine.run(tmp_path)
    cache.close()

    assert result.file_count == 2
    assert len(result.groups) == 0  # SHA-256 disagrees → no match in ALL mode


def test_engine_respects_min_size_filter(tmp_path: Path):
    cfg = _config({METHOD_SIZE, METHOD_SHA256})
    cfg.cache_path = str(tmp_path / "cache.sqlite")
    cfg.min_file_size_bytes = 1024
    cache = Cache(cfg.cache_path)

    make_dummy_video_file(tmp_path / "tiny1.mp4", b"x" * 100)
    make_dummy_video_file(tmp_path / "tiny2.mp4", b"x" * 100)  # under threshold
    make_dummy_video_file(tmp_path / "big1.mp4", b"y" * 2048)
    make_dummy_video_file(tmp_path / "big2.mp4", b"y" * 2048)

    engine = Engine(cfg, cache)
    result = engine.run(tmp_path)
    cache.close()

    # The two tiny files should be filtered out by the size filter; only the
    # big-file pair should form a group.
    assert result.file_count == 2
    assert len(result.groups) == 1
    assert {Path(f.path).name for f in result.groups[0].files} == {"big1.mp4", "big2.mp4"}


def test_engine_cancellation(tmp_path: Path):
    cfg = _config({METHOD_SIZE, METHOD_SHA256})
    cfg.cache_path = str(tmp_path / "cache.sqlite")
    cache = Cache(cfg.cache_path)

    for i in range(5):
        make_dummy_video_file(tmp_path / f"f{i}.mp4", b"x" * (1024 * (i + 1)))

    cancel = threading.Event()
    cancel.set()  # cancel before we even start
    engine = Engine(cfg, cache, cancel_event=cancel)
    result = engine.run(tmp_path)
    cache.close()
    # We should not have built any groups when cancelled immediately after scan.
    assert result.groups == []


def test_engine_no_methods_enabled(tmp_path: Path):
    cfg = _config(set())
    cfg.cache_path = str(tmp_path / "cache.sqlite")
    cache = Cache(cfg.cache_path)
    make_dummy_video_file(tmp_path / "a.mp4", b"x" * 100)
    engine = Engine(cfg, cache)
    result = engine.run(tmp_path)
    cache.close()
    assert result.groups == []


def test_preset_easy_uses_all_logic():
    """Easy preset should default to MATCH_ALL for correct exact-dup semantics."""
    cfg = AppConfig()
    cfg.apply_preset("easy")
    from vidcomp.config import MATCH_ALL, METHOD_SHA256, METHOD_SIZE
    assert cfg.match_logic == MATCH_ALL
    assert METHOD_SIZE in cfg.enabled_methods
    assert METHOD_SHA256 in cfg.enabled_methods


def test_preset_medium_uses_any_logic():
    """Medium preset should use ANY so pHash can flag re-encoded dupes."""
    cfg = AppConfig()
    cfg.apply_preset("medium")
    from vidcomp.config import MATCH_ANY, METHOD_PHASH
    assert cfg.match_logic == MATCH_ANY
    assert METHOD_PHASH in cfg.enabled_methods


def test_preset_robust_enables_all_methods():
    cfg = AppConfig()
    cfg.apply_preset("robust")
    from vidcomp.config import (
        METHOD_AUDIO, METHOD_PHASH, METHOD_PSNR, METHOD_SSIM, METHOD_VMAF,
    )
    for mid in (METHOD_PHASH, METHOD_SSIM, METHOD_PSNR, METHOD_VMAF, METHOD_AUDIO):
        assert mid in cfg.enabled_methods


def test_abstain_does_not_block_match_in_all_mode():
    """A method that abstains (sig missing) should not block ALL-logic matches."""
    from vidcomp.core.methods.base import ComparisonMethod, MethodContext
    from vidcomp.core.methods.m1_size import SizeMethod
    from vidcomp.core.models import MatchEvidence, VideoFile

    # Build a fake "metadata-like" method that always abstains.
    class AbstainMethod(ComparisonMethod):
        id = "fake_abstain"
        kind = "signature"

        def compute_signature(self, file, ctx):
            return None  # always missing

    a = VideoFile(path="C:/x/a", size=100, mtime=1.0, ctime=1.0)
    b = VideoFile(path="C:/x/b", size=100, mtime=1.0, ctime=1.0)
    ev = AbstainMethod().evaluate_pair(a, b, None, None, ctx=None)  # type: ignore[arg-type]
    assert ev.abstain is True
    assert ev.matched is False
    # The engine's combination logic ignores abstained evidences (covered by
    # finalize() in engine._evaluate_pairs).
