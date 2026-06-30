"""M5 - Perceptual hash (pHash) on sampled frames.

Samples ``frame_samples`` evenly-spaced frames per video, computes a perceptual
hash of each, and compares two videos by the average Hamming distance between
their aligned frame hashes.  Catches re-encoded, resized and re-muxed copies.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Optional

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext

log = logging.getLogger("vidcomp.methods.phash")

try:  # optional heavy deps
    import imagehash  # type: ignore
    from PIL import Image  # type: ignore

    _HAVE_IMAGEHASH = True
except Exception:  # pragma: no cover - import guard
    _HAVE_IMAGEHASH = False


def _phash_hex(image_path: str) -> Optional[str]:
    try:
        with Image.open(image_path) as im:
            return str(imagehash.phash(im))
    except Exception as exc:
        log.debug("phash of frame failed (%s): %s", image_path, exc)
        return None


def hamming_hex(a: str, b: str) -> int:
    """Hamming distance between two equal-length hex perceptual hashes."""
    ha = imagehash.hex_to_hash(a)
    hb = imagehash.hex_to_hash(b)
    return ha - hb


def average_distance(pa: list[str], pb: list[str]) -> Optional[float]:
    """Average per-frame Hamming distance across aligned frame hashes."""
    if not pa or not pb:
        return None
    n = min(len(pa), len(pb))
    if n == 0:
        return None
    total = 0
    for i in range(n):
        try:
            total += hamming_hex(pa[i], pb[i])
        except Exception:
            return None
    return total / n


class PerceptualHashMethod(ComparisonMethod):
    """Sampled-frame perceptual hashing with a Hamming-distance threshold."""

    method_id = MethodId.PHASH
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        return _HAVE_IMAGEHASH and ctx.tools.has_ffmpeg

    def prepare(self, vf: VideoFile, ctx: MethodContext) -> None:
        if vf.phashes is not None:
            return
        if not self.available(ctx):
            return
        count = int(getattr(ctx.options, "frame_samples", 9))
        duration = vf.info.duration if vf.info else None
        frames_dir = ctx.frames_dir_for(vf)
        try:
            frames = ctx.tools.extract_frames(vf.path, count, duration, frames_dir)
            hashes: list[str] = []
            for fp in frames:
                h = _phash_hex(fp)
                if h:
                    hashes.append(h)
            vf.phashes = hashes
        finally:
            # Frames are transient; the hashes are what we cache.
            shutil.rmtree(frames_dir, ignore_errors=True)

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        if not a.phashes or not b.phashes:
            return None
        avg = average_distance(a.phashes, b.phashes)
        if avg is None:
            return None
        threshold = int(getattr(ctx.options, "phash_threshold", 8))
        if avg <= threshold:
            # Map distance to a 0..1 score (0 distance -> 1.0).
            score = max(0.0, 1.0 - (avg / 64.0))
            return MatchEvidence(
                method=MethodId.PHASH,
                score=round(score, 3),
                detail=f"avg pHash distance {avg:.1f} <= {threshold}",
            )
        return None
