"""Tests for the engine's candidate generation, ANY/ALL logic and grouping."""

from __future__ import annotations

from vidcomp.config import ScanOptions
from vidcomp.core.engine import DuplicateEngine, _UnionFind
from vidcomp.core.models import MatchLogic, MediaInfo, MethodId

from .conftest import StubTools, make_video


def _info(duration, w=1920, h=1080, codec="h264", fps=30.0, ch=2, br=5_000_000):
    return MediaInfo(duration=duration, width=w, height=h, video_codec=codec,
                     fps=fps, audio_channels=ch, bitrate=br, has_video=True, ok=True)


def test_union_find():
    uf = _UnionFind(5)
    uf.union(0, 1)
    uf.union(1, 2)
    uf.union(3, 4)
    assert uf.find(0) == uf.find(2)
    assert uf.find(0) != uf.find(3)


def test_size_only_grouping():
    files = [
        make_video("a.mp4", 100, info=_info(60)),
        make_video("b.mp4", 100, info=_info(60)),
        make_video("c.mp4", 250, info=_info(99)),
    ]
    opts = ScanOptions(enabled_methods={MethodId.SIZE}, match_logic=MatchLogic.ANY)
    eng = DuplicateEngine(StubTools(), opts)
    groups = eng.run(files)
    assert len(groups) == 1
    assert {f.name for f in groups[0].files} == {"a.mp4", "b.mp4"}


def test_size_alone_is_not_a_match():
    # Same byte size but different content/metadata must NOT be grouped:
    # M1 is a pre-filter, not a standalone vote, when stronger methods exist.
    files = [
        make_video("a.mp4", 100, info=_info(60)),
        make_video("b.mp4", 100, info=_info(999)),
    ]
    opts = ScanOptions(
        enabled_methods={MethodId.SIZE, MethodId.METADATA}, match_logic=MatchLogic.ANY
    )
    groups = DuplicateEngine(StubTools(), opts).run(files)
    assert groups == []


def test_any_vs_all_logic(tmp_path):
    # f1/f2 are byte-identical; f3 is a "re-encode": different bytes but the
    # same duration/resolution/codec metadata.
    identical = b"VID" + b"\x00" * 8000
    f1 = tmp_path / "f1.mp4"
    f2 = tmp_path / "f2.mp4"
    f3 = tmp_path / "f3.mp4"
    f1.write_bytes(identical)
    f2.write_bytes(identical)
    f3.write_bytes(b"OTHER" + b"\x01" * 5000)  # different size + content

    files = [
        make_video(str(f1), f1.stat().st_size, info=_info(120.0)),
        make_video(str(f2), f2.stat().st_size, info=_info(120.0)),
        make_video(str(f3), f3.stat().st_size, info=_info(120.0)),
    ]
    methods = {MethodId.SHA256, MethodId.METADATA}

    any_opts = ScanOptions(enabled_methods=set(methods), match_logic=MatchLogic.ANY)
    any_groups = DuplicateEngine(StubTools(), any_opts).run([
        make_video(str(f1), f1.stat().st_size, info=_info(120.0)),
        make_video(str(f2), f2.stat().st_size, info=_info(120.0)),
        make_video(str(f3), f3.stat().st_size, info=_info(120.0)),
    ])
    # ANY: f3 matches f1/f2 by metadata, so all three collapse into one group.
    assert len(any_groups) == 1
    assert len(any_groups[0].files) == 3

    all_opts = ScanOptions(enabled_methods=set(methods), match_logic=MatchLogic.ALL)
    all_groups = DuplicateEngine(StubTools(), all_opts).run(files)
    # ALL: f3 fails SHA-256, so only the byte-identical f1+f2 group.
    assert len(all_groups) == 1
    assert {f.name for f in all_groups[0].files} == {"f1.mp4", "f2.mp4"}


def test_duration_bucket_candidates_for_reencode():
    # Different sizes (re-encode) but near-identical duration + metadata.
    files = [
        make_video("orig.mp4", 5_000_000, info=_info(120.0)),
        make_video("reenc.mp4", 2_000_000, info=_info(120.3)),
    ]
    opts = ScanOptions(enabled_methods={MethodId.METADATA}, match_logic=MatchLogic.ANY)
    groups = DuplicateEngine(StubTools(), opts).run(files)
    assert len(groups) == 1
    assert len(groups[0].files) == 2


def test_no_methods_returns_empty():
    files = [make_video("a.mp4", 1), make_video("b.mp4", 1)]
    opts = ScanOptions(enabled_methods=set())
    assert DuplicateEngine(StubTools(), opts).run(files) == []
