"""M5 — perceptual hash on uniformly-sampled frames (with mean-Hamming match).

For each video we extract N frames at uniform timestamps, perceptually hash
each frame with ``imagehash.phash`` (64-bit pHash), and store the
concatenated bits as a single bytes blob.  Two videos match when the
mean Hamming distance across the per-frame pHashes is below the configured
threshold.
"""

from __future__ import annotations

import logging
import struct
import tempfile
from pathlib import Path
from typing import List, Optional

import numpy as np

try:
    import imagehash
    from PIL import Image
except Exception:  # pragma: no cover — handled at runtime
    imagehash = None  # type: ignore
    Image = None  # type: ignore

from ...config import METHOD_PHASH
from .. import media
from ..models import MatchEvidence, VideoFile
from .base import ComparisonMethod, MethodContext
from .m4_metadata import get_or_fetch_metadata

LOG = logging.getLogger(__name__)

_HASH_SIZE = 8  # 8x8 = 64-bit pHash per frame
_BYTES_PER_FRAME = 8


class PerceptualHashMethod(ComparisonMethod):
    id = METHOD_PHASH
    display_name = "Perceptual hash (per-frame pHash)"
    kind = "signature"
    description = (
        "Samples N frames spread across each video, hashes them with a perceptual "
        "hash, then compares two videos by the mean Hamming distance of their "
        "frame hashes. Catches re-encoded and resized duplicates."
    )

    # ------------------------------------------------------------------
    def compute_signature(self, file: VideoFile, ctx: MethodContext) -> Optional[bytes]:
        if imagehash is None or Image is None:
            LOG.warning("imagehash/Pillow unavailable — pHash disabled")
            return None
        n = max(1, int(getattr(ctx.config, "phash_frames", 9)))
        cache_kind = f"{self.id}_v1_n{n}"
        cached = ctx.cache.get_artifact(file.path, file.size, file.mtime, cache_kind)
        if cached is not None and len(cached) >= _BYTES_PER_FRAME:
            return cached
        md = get_or_fetch_metadata(file, ctx)
        duration = md.duration_sec if md is not None else None
        if not duration or duration <= 0:
            duration = 1.0
        timestamps = media.compute_uniform_timestamps(duration, n)

        with tempfile.TemporaryDirectory(prefix="vidcomp_phash_") as tmp:
            tmp_path = Path(tmp)
            try:
                frame_paths = media.extract_frames_to_dir(
                    file.path, timestamps, tmp_path,
                    cancel_event=ctx.cancel_event,
                    size=(256, 144),
                )
            except Exception as exc:  # noqa: BLE001
                LOG.warning("frame extraction failed for %s: %s", file.path, exc)
                return None
            if not frame_paths:
                return None
            blob = b""
            for fp in frame_paths:
                if ctx.is_cancelled():
                    return None
                try:
                    with Image.open(fp) as img:
                        ph = imagehash.phash(img, hash_size=_HASH_SIZE)
                    # imagehash.hash is a numpy bool array of shape (8,8) → 64 bits
                    bits = np.packbits(ph.hash.flatten().astype(np.uint8))
                    blob += bits.tobytes()
                except Exception as exc:  # noqa: BLE001
                    LOG.debug("pHash failed on %s: %s", fp, exc)
                    continue

        if not blob:
            return None
        ctx.cache.put_artifact(file.path, file.size, file.mtime, cache_kind, blob)
        return blob

    # ------------------------------------------------------------------
    def evaluate_pair(
        self,
        a: VideoFile,
        b: VideoFile,
        sig_a: Optional[bytes],
        sig_b: Optional[bytes],
        ctx: MethodContext,
    ) -> MatchEvidence:
        if not sig_a or not sig_b:
            return MatchEvidence(
                self.id, False, 0.0, detail="no pHash", abstain=True
            )
        distance = mean_hamming(sig_a, sig_b)
        if distance is None:
            return MatchEvidence(
                self.id, False, 0.0, detail="no frames", abstain=True
            )
        threshold = float(getattr(ctx.config, "phash_threshold", 8))
        matched = distance <= threshold
        return MatchEvidence(
            method_id=self.id,
            matched=matched,
            score=float(distance),
            detail=(f"pHash mean Hamming={distance:.1f} "
                    f"{'≤' if matched else '>'} {threshold:.0f}"),
        )


# ---------------------------------------------------------------------------
# Pure functions used by the engine for pHash pair distances
# ---------------------------------------------------------------------------
def split_frames(blob: bytes) -> List[int]:
    """Split a concatenated pHash blob into one 64-bit int per frame."""
    if not blob:
        return []
    out: List[int] = []
    for i in range(0, len(blob) - (_BYTES_PER_FRAME - 1), _BYTES_PER_FRAME):
        chunk = blob[i:i + _BYTES_PER_FRAME]
        if len(chunk) == _BYTES_PER_FRAME:
            out.append(struct.unpack(">Q", chunk)[0])
    return out


def mean_hamming(a: bytes, b: bytes) -> Optional[float]:
    """Mean per-frame Hamming distance between two pHash blobs (0..64).

    If the blobs have different frame counts we compare the leading
    ``min(len_a, len_b)`` frames so a partially-cached signature still works.
    Returns ``None`` when either blob has no frames.
    """
    fa = split_frames(a)
    fb = split_frames(b)
    n = min(len(fa), len(fb))
    if n == 0:
        return None
    total = 0
    for i in range(n):
        total += (fa[i] ^ fb[i]).bit_count()
    return total / n
