"""Tests for the perceptual-hash distance helpers in :mod:`m5_phash`."""

from __future__ import annotations

import struct

import pytest

from vidcomp.core.methods.m5_phash import mean_hamming, split_frames


def _blob_from_ints(ints):
    """Pack a list of 64-bit ints into a single bytes blob."""
    return b"".join(struct.pack(">Q", x) for x in ints)


def test_split_frames_round_trip():
    ints = [0x0123456789ABCDEF, 0xFEDCBA9876543210, 0xAAAAAAAAAAAAAAAA]
    blob = _blob_from_ints(ints)
    assert split_frames(blob) == ints


def test_mean_hamming_identical():
    blob = _blob_from_ints([0x00, 0xFF])
    assert mean_hamming(blob, blob) == 0.0


def test_mean_hamming_all_ones():
    a = _blob_from_ints([0x0000000000000000])
    b = _blob_from_ints([0xFFFFFFFFFFFFFFFF])
    assert mean_hamming(a, b) == 64.0


def test_mean_hamming_per_frame_average():
    a = _blob_from_ints([0x0, 0x0])
    b = _blob_from_ints([0xFFFFFFFFFFFFFFFF, 0x0])
    # Frame 1: 64 bits differ. Frame 2: 0 bits differ. Mean = 32.
    assert mean_hamming(a, b) == 32.0


def test_mean_hamming_empty_returns_none():
    assert mean_hamming(b"", b"") is None
    assert mean_hamming(b"", _blob_from_ints([0])) is None


def test_mean_hamming_truncates_to_shortest():
    a = _blob_from_ints([0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF])
    b = _blob_from_ints([0x0])
    # Only the leading frame is compared.
    assert mean_hamming(a, b) == 64.0
