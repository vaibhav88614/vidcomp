"""Comparison-method plug-ins (M1..M9).

Each method exposes a class deriving from :class:`vidcomp.core.methods.base.ComparisonMethod`.
The :data:`METHOD_REGISTRY` mapping below is the single source of truth that the
engine and GUI use to discover available methods.

Methods M8 (VMAF) and M9 (audio) are only *available* if their backing
command-line tools (``ffmpeg`` with ``libvmaf`` and ``fpcalc`` respectively)
are present.  They are still registered so the GUI can display them disabled.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Set, Type

from .base import ComparisonMethod
from .m1_size import SizeMethod
from .m2_sha256 import Sha256Method
from .m3_partial_hash import PartialHashMethod
from .m4_metadata import MetadataMethod
from .m5_phash import PerceptualHashMethod
from .m6_ssim import SsimMethod
from .m7_psnr import PsnrMethod
from .m8_vmaf import VmafMethod
from .m9_audio import AudioFingerprintMethod

#: Ordered registry of every comparison method, cheapest first.
METHOD_REGISTRY: Dict[str, Type[ComparisonMethod]] = {
    SizeMethod.id: SizeMethod,
    PartialHashMethod.id: PartialHashMethod,
    Sha256Method.id: Sha256Method,
    MetadataMethod.id: MetadataMethod,
    PerceptualHashMethod.id: PerceptualHashMethod,
    SsimMethod.id: SsimMethod,
    PsnrMethod.id: PsnrMethod,
    VmafMethod.id: VmafMethod,
    AudioFingerprintMethod.id: AudioFingerprintMethod,
}

ALL_METHOD_IDS: List[str] = list(METHOD_REGISTRY.keys())


def get_method(method_id: str) -> Type[ComparisonMethod]:
    """Look up a method class by id."""
    return METHOD_REGISTRY[method_id]


def instantiate_methods(method_ids: Iterable[str]) -> List[ComparisonMethod]:
    """Return instances for the given method ids (skips unknown ids)."""
    out: List[ComparisonMethod] = []
    for mid in method_ids:
        cls = METHOD_REGISTRY.get(mid)
        if cls is not None:
            out.append(cls())
    return out


def methods_for_preset(preset: str) -> Set[str]:
    """Return the canonical enabled-method set for a preset name.

    Presets:
      * ``easy``    — size, partial-hash, sha256, metadata
      * ``medium``  — easy + perceptual hash
      * ``robust``  — medium + ssim, psnr, vmaf, audio
    """
    preset = preset.lower()
    easy = {SizeMethod.id, PartialHashMethod.id, Sha256Method.id, MetadataMethod.id}
    if preset == "easy":
        return set(easy)
    if preset == "medium":
        return easy | {PerceptualHashMethod.id}
    if preset == "robust":
        return easy | {
            PerceptualHashMethod.id,
            SsimMethod.id,
            PsnrMethod.id,
            VmafMethod.id,
            AudioFingerprintMethod.id,
        }
    raise ValueError(f"Unknown preset: {preset!r}")


__all__ = [
    "METHOD_REGISTRY",
    "ALL_METHOD_IDS",
    "ComparisonMethod",
    "get_method",
    "instantiate_methods",
    "methods_for_preset",
]
