"""M4 - Metadata comparison via ffprobe.

Compares duration, resolution, codec, bitrate, fps and audio channels with
sensible tolerances.  Catches exact copies and near-exact remuxes / re-encodes
and also acts as a cheap gate before perceptual/structural comparisons.

To avoid false positives where two completely unrelated clips happen to share a
duration (e.g. two 30-minute 1080p H.264 episodes from different shows), this
method requires *all* of the following before declaring a match:

* duration agrees within tolerance (the strongest single metadata signal);
* **resolution is identical** (a real duplicate / re-encode never changes
  aspect or pixel dimensions silently — and if it does, M5 pHash / M6 SSIM
  will catch it instead);
* at least **two additional** attributes agree from {codec, fps,
  audio channels, bitrate-within-10 %}.

That floor (4 matching attributes including duration + resolution) keeps every
intentional remux / re-encode case while rejecting accidental coincidences.
"""

from __future__ import annotations

from typing import Optional

from ..models import MatchEvidence, MediaInfo, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext


def _duration_close(a: Optional[float], b: Optional[float], tol: float = 1.0) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol, 0.02 * max(a, b))


class MetadataMethod(ComparisonMethod):
    """Match on container/stream metadata similarity."""

    method_id = MethodId.METADATA
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        return ctx.tools.has_ffprobe

    def prepare(self, vf: VideoFile, ctx: MethodContext) -> None:
        if vf.info is None:
            vf.info = ctx.tools.probe(vf.path)

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        ia, ib = a.info, b.info
        if not ia or not ib or not ia.ok or not ib.ok:
            return None

        # Hard gate 1: duration must agree (strongest single signal).
        if not _duration_close(ia.duration, ib.duration):
            return None

        # Hard gate 2: resolution must be identical when both are known.
        # If either side lacks resolution info we cannot use this as a gate,
        # but we also cannot count it as a match — fall through and require
        # extra attributes from the secondary list instead.
        resolution_known = bool(ia.resolution and ib.resolution)
        if resolution_known and ia.resolution != ib.resolution:
            return None

        matches: list[str] = ["duration"]
        score_parts: list[float] = [1.0]

        if resolution_known:
            matches.append("resolution")
            score_parts.append(1.0)

        # Secondary attributes — at least two of these must agree.
        secondary: list[str] = []
        if ia.video_codec and ib.video_codec and ia.video_codec == ib.video_codec:
            secondary.append("codec")
        if ia.fps and ib.fps and abs(ia.fps - ib.fps) <= 0.5:
            secondary.append("fps")
        if (
            ia.audio_channels
            and ib.audio_channels
            and ia.audio_channels == ib.audio_channels
        ):
            secondary.append("audio-ch")
        if ia.bitrate and ib.bitrate:
            hi = max(ia.bitrate, ib.bitrate)
            if hi and abs(ia.bitrate - ib.bitrate) / hi <= 0.1:
                secondary.append("bitrate")

        if len(secondary) < 2:
            return None

        matches.extend(secondary)
        score_parts.extend([1.0] * len(secondary))

        score = sum(score_parts) / len(score_parts)
        return MatchEvidence(
            method=MethodId.METADATA,
            score=round(score, 3),
            detail="metadata match: " + ", ".join(matches),
        )
