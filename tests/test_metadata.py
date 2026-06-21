"""Tests for ffprobe JSON parsing in :mod:`vidcomp.core.media`."""

from __future__ import annotations

import json

import pytest

from vidcomp.core import media


_SAMPLE_JSON = json.dumps({
    "format": {
        "duration": "123.45",
        "bit_rate": "5000000",
    },
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "60000/1001",
            "bit_rate": "4500000",
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "sample_rate": "48000",
        },
    ],
})


def test_parse_ffprobe_json_full():
    md = media.parse_ffprobe_json(_SAMPLE_JSON)
    assert md.has_video is True
    assert md.has_audio is True
    assert md.duration_sec == pytest.approx(123.45)
    assert md.width == 1920
    assert md.height == 1080
    assert md.resolution == (1920, 1080)
    assert md.video_codec == "h264"
    assert md.bit_rate == 5_000_000
    assert md.fps == pytest.approx(60000 / 1001, rel=1e-6)
    assert md.audio_codec == "aac"
    assert md.audio_channels == 2
    assert md.audio_sample_rate == 48000


def test_parse_ffprobe_json_video_only():
    payload = json.dumps({
        "format": {},
        "streams": [
            {"codec_type": "video", "codec_name": "vp9", "width": 640, "height": 360,
             "r_frame_rate": "30/1"},
        ],
    })
    md = media.parse_ffprobe_json(payload)
    assert md.has_video and not md.has_audio
    assert md.fps == pytest.approx(30.0)
    assert md.resolution_str == "640x360"


def test_parse_ffprobe_json_empty():
    md = media.parse_ffprobe_json("{}")
    assert md.has_video is False
    assert md.has_audio is False
    assert md.duration_sec is None
    assert md.resolution is None


def test_parse_fraction_handles_zero_denom():
    # Internal helper but worth exercising directly.
    assert media._parse_fraction("0/0") is None
    assert media._parse_fraction("30/0") is None
    assert media._parse_fraction("24") == pytest.approx(24.0)
    assert media._parse_fraction(None) is None
