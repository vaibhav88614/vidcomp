"""Unit tests for the individual comparison methods (M1-M9, sans M4)."""

from __future__ import annotations

import os

import pytest

from vidcomp.core.methods.m1_size import SizeMethod
from vidcomp.core.methods.m2_sha256 import Sha256Method, sha256_of
from vidcomp.core.methods.m3_partial_hash import PartialHashMethod, partial_hash_of
from vidcomp.core.methods.m9_audio import _bit_similarity, _to_ints
from vidcomp.core.models import MediaInfo

from .conftest import make_video


def test_size_match(ctx):
    a = make_video("a.mp4", 100)
    b = make_video("b.mp4", 100)
    c = make_video("c.mp4", 101)
    m = SizeMethod()
    assert m.compare(a, b, ctx) is not None
    assert m.compare(a, c, ctx) is None


def test_size_zero_no_match(ctx):
    a = make_video("a.mp4", 0)
    b = make_video("b.mp4", 0)
    assert SizeMethod().compare(a, b, ctx) is None


def test_sha256_and_partial(tmp_path, ctx):
    p1 = tmp_path / "one.bin"
    p2 = tmp_path / "two.bin"
    data = os.urandom(4096) + b"x" * 100
    p1.write_bytes(data)
    p2.write_bytes(data)
    p3 = tmp_path / "three.bin"
    p3.write_bytes(os.urandom(4096) + b"y" * 100)

    assert sha256_of(str(p1)) == sha256_of(str(p2))
    assert sha256_of(str(p1)) != sha256_of(str(p3))

    a = make_video(str(p1), p1.stat().st_size)
    b = make_video(str(p2), p2.stat().st_size)
    c = make_video(str(p3), p3.stat().st_size)
    sha = Sha256Method()
    for vf in (a, b, c):
        sha.prepare(vf, ctx)
    assert sha.compare(a, b, ctx) is not None
    assert sha.compare(a, c, ctx) is None

    ph = PartialHashMethod()
    for vf in (a, b, c):
        ph.prepare(vf, ctx)
    assert ph.compare(a, b, ctx) is not None


def test_partial_hash_distinguishes_size(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abcdef")
    h1 = partial_hash_of(str(p), 6, 1024)
    h2 = partial_hash_of(str(p), 999, 1024)  # different declared size
    assert h1 != h2


def test_audio_similarity():
    fp = ",".join(str(i) for i in range(200))
    assert _bit_similarity(_to_ints(fp), _to_ints(fp)) == pytest.approx(1.0)
    different = ",".join(str((i * 2654435761) & 0xFFFFFFFF) for i in range(200))
    sim = _bit_similarity(_to_ints(fp), _to_ints(different))
    assert sim is not None and sim < 0.95


def test_phash_distance():
    imagehash = pytest.importorskip("imagehash")
    from vidcomp.core.methods.m5_phash import average_distance

    a = [str(imagehash.hex_to_hash("f" * 16))]
    b = [str(imagehash.hex_to_hash("f" * 16))]
    assert average_distance(a, b) == 0
