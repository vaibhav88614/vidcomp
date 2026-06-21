"""Base class + shared context for comparison methods.

Each method exposes:
    * ``compute_signature(file, ctx)`` — for signature-style methods, returns
      a small per-file fingerprint (cached).  Pure-pairwise methods return
      ``None`` here.
    * ``evaluate_pair(a, b, sig_a, sig_b, ctx)`` — the single entry point the
      engine uses to ask "do these two files match according to me?".

The default ``evaluate_pair`` performs exact signature equality (the common
case for M1, M2, M3, M4).  Approximate-signature methods (pHash, audio) and
pure-pairwise methods (SSIM, PSNR, VMAF) override it.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..cache import Cache
from ..models import MatchEvidence, MediaMetadata, VideoFile

LOG = logging.getLogger(__name__)


@dataclass
class MethodContext:
    """Shared resources passed to every method invocation."""

    cache: Cache
    cancel_event: threading.Event
    config: Any                                                # vidcomp.config.AppConfig
    metadata_cache: Dict[str, MediaMetadata] = field(default_factory=dict)

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()


class ComparisonMethod:
    """Abstract base class for all M1..M9 methods.

    Subclasses set:
        id          : stable string id (matches :mod:`vidcomp.config`).
        display_name: human-friendly name for the GUI.
        kind        : "signature" (has compute_signature) or "pairwise".
    """

    id: str = ""
    display_name: str = ""
    kind: str = "signature"
    description: str = ""

    # ------------------------------------------------------------------
    def compute_signature(
        self, file: VideoFile, ctx: MethodContext
    ) -> Optional[Any]:
        """Compute & cache the per-file fingerprint.  ``None`` means skip."""
        return None

    # ------------------------------------------------------------------
    def evaluate_pair(
        self,
        a: VideoFile,
        b: VideoFile,
        sig_a: Optional[Any],
        sig_b: Optional[Any],
        ctx: MethodContext,
    ) -> MatchEvidence:
        """Decide whether two files match.

        Default behaviour is "signatures are non-None and equal".  Override
        for approximate similarity or pure-pairwise comparison.
        """
        if sig_a is None or sig_b is None:
            return MatchEvidence(
                self.id, False, 0.0, detail="missing signature", abstain=True
            )
        matched = sig_a == sig_b
        return MatchEvidence(
            method_id=self.id,
            matched=matched,
            score=1.0 if matched else 0.0,
            detail="signatures match" if matched else "signatures differ",
        )

    # ------------------------------------------------------------------
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id!r}>"
