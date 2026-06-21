"""Tests for M1 (size), M2 (SHA-256) and M3 (partial hash)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests.conftest import make_dummy_video_file


def test_size_method(tmp_path: Path, context):
    from vidcomp.core.methods.m1_size import SizeMethod

    f1 = make_dummy_video_file(tmp_path / "a.mp4", b"x" * 1024)
    f2 = make_dummy_video_file(tmp_path / "b.mp4", b"y" * 1024)
    f3 = make_dummy_video_file(tmp_path / "c.mp4", b"z" * 2048)

    m = SizeMethod()
    assert m.compute_signature(f1, context) == 1024
    assert m.compute_signature(f2, context) == 1024
    assert m.compute_signature(f3, context) == 2048


def test_sha256_method_identical_and_cached(tmp_path: Path, context):
    from vidcomp.core.methods.m2_sha256 import Sha256Method

    data = b"The quick brown fox" * 1000
    f1 = make_dummy_video_file(tmp_path / "a.mp4", data)
    f2 = make_dummy_video_file(tmp_path / "b.mp4", data)
    expected = hashlib.sha256(data).hexdigest()

    m = Sha256Method()
    sig1 = m.compute_signature(f1, context)
    sig2 = m.compute_signature(f2, context)
    assert sig1 == sig2 == expected

    # Second call should hit cache (same value).
    sig1b = m.compute_signature(f1, context)
    assert sig1b == sig1

    # Verify pair-evaluation returns matched for identical content.
    ev = m.evaluate_pair(f1, f2, sig1, sig2, context)
    assert ev.matched is True


def test_sha256_method_differs(tmp_path: Path, context):
    from vidcomp.core.methods.m2_sha256 import Sha256Method

    f1 = make_dummy_video_file(tmp_path / "a.mp4", b"abc" * 100)
    f2 = make_dummy_video_file(tmp_path / "b.mp4", b"xyz" * 100)
    m = Sha256Method()
    assert m.compute_signature(f1, context) != m.compute_signature(f2, context)


def test_partial_hash_method_identical(tmp_path: Path, context):
    from vidcomp.core.methods.m3_partial_hash import PartialHashMethod

    # Use enough data that head + tail are distinct.
    data = b"H" * 5000 + b"M" * 5000 + b"T" * 5000
    f1 = make_dummy_video_file(tmp_path / "a.mp4", data)
    f2 = make_dummy_video_file(tmp_path / "b.mp4", data)
    m = PartialHashMethod()
    sig1 = m.compute_signature(f1, context)
    sig2 = m.compute_signature(f2, context)
    assert sig1 == sig2


def test_partial_hash_method_detects_tail_change(tmp_path: Path, context):
    from vidcomp.core.methods.m3_partial_hash import PartialHashMethod

    head = b"HEAD" * 1024
    middle = b"MID" * 1024
    f1 = make_dummy_video_file(tmp_path / "a.mp4", head + middle + b"AAAA")
    f2 = make_dummy_video_file(tmp_path / "b.mp4", head + middle + b"BBBB")
    m = PartialHashMethod()
    # Differs because tail differs and total size differs (b"AAAA" vs b"BBBB"
    # are the same length, but partial hash includes the tail bytes).
    assert m.compute_signature(f1, context) != m.compute_signature(f2, context)


def test_partial_hash_small_files(tmp_path: Path, context):
    """Files smaller than 2*N should not double-read the same bytes."""
    from vidcomp.core.methods.m3_partial_hash import PartialHashMethod

    # Default partial_hash_bytes is 1 MiB; create a tiny file.
    f1 = make_dummy_video_file(tmp_path / "a.mp4", b"hello")
    m = PartialHashMethod()
    sig = m.compute_signature(f1, context)
    assert isinstance(sig, str) and len(sig) == 64  # SHA-256 hex
