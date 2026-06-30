"""Pluggable comparison methods (M1-M9, except M4 which has been removed).

Each method is a small class implementing :class:`ComparisonMethod`.  The
engine instantiates the enabled methods and uses them in two phases:

* ``prepare(vf, ctx)`` computes any per-file signature (hash, perceptual hash,
  fingerprint) and caches it on the :class:`VideoFile`.
* ``compare(a, b, ctx)`` returns :class:`MatchEvidence` when two files match
  according to that method's threshold, otherwise ``None``.

Cheap methods (size/hash/pHash) are also able to bucket files quickly;
the engine uses that to avoid an O(n^2) explosion before escalating to the
expensive pairwise metrics (SSIM/PSNR/VMAF/audio).

M4 (ffprobe metadata matching) was removed because, in practice, comparing
duration / resolution / codec / bitrate cannot reliably distinguish two
unrelated clips that happen to share those attributes (e.g. two different
1080p H.264 episodes of the same length).  Real re-encodes and re-muxes are
caught by M2/M3 (byte-level) or M5–M8 (perceptual / structural).  The
ffprobe-derived :class:`MediaInfo` is still produced and cached for the other
methods that genuinely need it (M5 pHash sanity guards, SSIM/PSNR/VMAF).
"""

from __future__ import annotations

from .base import ComparisonMethod, MethodContext
from .m1_size import SizeMethod
from .m2_sha256 import Sha256Method
from .m3_partial_hash import PartialHashMethod
from .m5_phash import PerceptualHashMethod
from .m6_ssim import SsimMethod
from .m7_psnr import PsnrMethod
from .m8_vmaf import VmafMethod
from .m9_audio import AudioFingerprintMethod
from ..models import MethodId

# Registry mapping a method id to its implementation class.
METHOD_REGISTRY: dict[MethodId, type[ComparisonMethod]] = {
    MethodId.SIZE: SizeMethod,
    MethodId.SHA256: Sha256Method,
    MethodId.PARTIAL_HASH: PartialHashMethod,
    MethodId.PHASH: PerceptualHashMethod,
    MethodId.SSIM: SsimMethod,
    MethodId.PSNR: PsnrMethod,
    MethodId.VMAF: VmafMethod,
    MethodId.AUDIO: AudioFingerprintMethod,
}


def build_method(method_id: MethodId) -> ComparisonMethod:
    return METHOD_REGISTRY[method_id]()


__all__ = [
    "ComparisonMethod",
    "MethodContext",
    "METHOD_REGISTRY",
    "build_method",
    "SizeMethod",
    "Sha256Method",
    "PartialHashMethod",
    "PerceptualHashMethod",
    "SsimMethod",
    "PsnrMethod",
    "VmafMethod",
    "AudioFingerprintMethod",
]
