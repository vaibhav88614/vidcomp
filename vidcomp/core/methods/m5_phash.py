"""M5 - Perceptual hash (pHash) on sampled frames.

Samples ``frame_samples`` evenly-spaced frames per video, computes a 64-bit
perceptual hash of each, and compares two videos by the average Hamming
distance between their aligned frame hashes.  Catches re-encoded, resized and
re-muxed copies.

The pHash itself is computed with OpenCV + NumPy (both already required for the
rest of the app), so **no separate ``phash`` C++ library, ``imagehash`` package
or ``scipy`` install is needed**.  Install of the upstream ``phash`` PyPI
package fails on Windows for most users; the built-in implementation avoids
that entirely.  If ``imagehash`` happens to be importable it is used as a
drop-in accelerator, but only as a fallback to the built-in path.

Before declaring a pair as matching, the method also requires:

* roughly compatible aspect ratios (re-encodes keep aspect even when resized);
* roughly compatible durations (otherwise sampled frames align to totally
  different content and coincidental dark / low-contrast frames can collide).

These guards close a class of false positives where two unrelated videos that
merely share dim intros / outros or low-detail content scored under the raw
Hamming threshold alone.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Optional

from ..models import MatchEvidence, MediaInfo, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext

log = logging.getLogger("vidcomp.methods.phash")

# Built-in backend (preferred): OpenCV + NumPy.
try:  # pragma: no cover - import guard
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    _HAVE_CV2 = True
except Exception:  # pragma: no cover - import guard
    _HAVE_CV2 = False

# Optional accelerator: imagehash + PIL.  Not required — only used if present.
try:  # pragma: no cover - import guard
    import imagehash  # type: ignore
    from PIL import Image  # type: ignore

    _HAVE_IMAGEHASH = True
except Exception:  # pragma: no cover - import guard
    _HAVE_IMAGEHASH = False

# Final fallback for image loading when cv2 is somehow missing.
try:  # pragma: no cover - import guard
    from PIL import Image as _PILImage  # type: ignore

    _HAVE_PIL = True
except Exception:  # pragma: no cover - import guard
    _HAVE_PIL = False


# --- hashing ---------------------------------------------------------------

def _phash_builtin(image_path: str) -> Optional[str]:
    """64-bit perceptual hash using OpenCV + NumPy.

    Pure-Python pHash recipe: convert to grayscale, resize to 32x32, take 2D
    DCT, keep the top-left 8x8 low-frequency block, threshold each coefficient
    against the median of the block (excluding the DC term) and pack the 64
    bits as a 16-char hex string.  Output format matches ``imagehash.phash``
    so cached hashes stay interchangeable.
    """
    if not _HAVE_CV2:
        return None
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None and _HAVE_PIL:
            with _PILImage.open(image_path) as im:  # type: ignore[union-attr]
                img = np.asarray(im.convert("L"), dtype=np.uint8)
        if img is None:
            return None
        small = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)
        dct = cv2.dct(small.astype(np.float32))
        block = dct[:8, :8].flatten()
        # Exclude the DC coefficient (block[0]) from the median, per standard
        # pHash; including it skews the threshold towards mostly-dark frames.
        median = float(np.median(block[1:]))
        bits = block > median
        # Pack 64 booleans into a 64-bit integer, then hex.
        value = 0
        for bit in bits:
            value = (value << 1) | int(bool(bit))
        return f"{value:016x}"
    except Exception as exc:
        log.debug("builtin pHash failed for %s: %s", image_path, exc)
        return None


def _phash_imagehash(image_path: str) -> Optional[str]:
    """Optional accelerator: compute pHash via ``imagehash`` if available."""
    if not _HAVE_IMAGEHASH:
        return None
    try:
        with Image.open(image_path) as im:  # type: ignore[union-attr]
            return str(imagehash.phash(im))  # type: ignore[union-attr]
    except Exception as exc:
        log.debug("imagehash pHash failed for %s: %s", image_path, exc)
        return None


def _phash_hex(image_path: str) -> Optional[str]:
    """Compute a 64-bit pHash for one image, preferring the built-in backend."""
    h = _phash_builtin(image_path)
    if h is not None:
        return h
    return _phash_imagehash(image_path)


def hamming_hex(a: str, b: str) -> int:
    """Hamming distance between two equal-length hex perceptual hashes.

    Works on any equal-length lowercase hex strings (e.g. 16 chars / 64 bits)
    and does not depend on ``imagehash`` being installed.
    """
    if len(a) != len(b):
        raise ValueError("hex hashes must be the same length")
    return (int(a, 16) ^ int(b, 16)).bit_count()


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


# --- sanity guards ---------------------------------------------------------

def _aspect_ratio(info: Optional[MediaInfo]) -> Optional[float]:
    if info is None or not info.width or not info.height:
        return None
    return float(info.width) / float(info.height)


def _aspect_compatible(a: VideoFile, b: VideoFile, rel_tol: float = 0.10) -> bool:
    """True if both files lack metadata or their aspect ratios agree within tol."""
    ra, rb = _aspect_ratio(a.info), _aspect_ratio(b.info)
    if ra is None or rb is None:
        return True  # unknown — do not reject on missing metadata
    hi = max(ra, rb)
    if hi <= 0:
        return True
    return abs(ra - rb) / hi <= rel_tol


def _duration_compatible(
    a: VideoFile,
    b: VideoFile,
    rel_tol: float = 0.10,
    abs_tol: float = 2.0,
) -> bool:
    """True if both files lack metadata or their durations agree within tol."""
    da = a.info.duration if a.info else None
    db = b.info.duration if b.info else None
    if da is None or db is None:
        return True
    return abs(da - db) <= max(abs_tol, rel_tol * max(da, db))


# --- method ----------------------------------------------------------------

class PerceptualHashMethod(ComparisonMethod):
    """Sampled-frame perceptual hashing with sanity-guarded Hamming threshold."""

    method_id = MethodId.PHASH
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        # Built-in backend (cv2 + numpy) is preferred; imagehash is an
        # acceptable fallback if cv2 is unavailable for some reason.  Either
        # way we need ffmpeg to sample frames from the video.
        return ctx.tools.has_ffmpeg and (_HAVE_CV2 or _HAVE_IMAGEHASH)

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

        # Sanity guards — refuse to call wildly mismatched videos "the same"
        # just because a handful of sampled frames happened to share low-detail
        # content (e.g. dark intros, gradients, letterbox bars).
        if not _aspect_compatible(a, b):
            log.debug(
                "phash: aspect-ratio mismatch, refusing match: %s vs %s",
                a.name, b.name,
            )
            return None
        if not _duration_compatible(a, b):
            log.debug(
                "phash: duration mismatch, refusing match: %s vs %s",
                a.name, b.name,
            )
            return None

        avg = average_distance(a.phashes, b.phashes)
        if avg is None:
            return None

        # Require a minimum number of overlapping frames before trusting the
        # mean distance — comparing 1–2 frames is too noisy to be a verdict.
        n = min(len(a.phashes), len(b.phashes))
        if n < 3:
            return None

        threshold = int(getattr(ctx.options, "phash_threshold", 8))
        if avg <= threshold:
            # Map distance to a 0..1 score (0 distance -> 1.0).
            score = max(0.0, 1.0 - (avg / 64.0))
            return MatchEvidence(
                method=MethodId.PHASH,
                score=round(score, 3),
                detail=(
                    f"avg pHash distance {avg:.1f} <= {threshold} "
                    f"over {n} frame(s)"
                ),
            )
        return None
