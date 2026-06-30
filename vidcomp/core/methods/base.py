"""Common interface and shared context for comparison methods."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..media import MediaTools
from ..models import MatchEvidence, MethodId, VideoFile

# Forward reference avoided; ScanOptions imported lazily where needed.


@dataclass
class MethodContext:
    """Shared services and scratch space passed to every method call."""

    tools: MediaTools
    options: object  # vidcomp.config.ScanOptions (avoid circular import)
    temp_dir: str
    is_cancelled: Callable[[], bool] = lambda: False

    # Memoization for expensive pairwise metrics, keyed by frozenset({pa, pb}).
    pair_cache: dict = field(default_factory=dict)

    def frames_dir_for(self, vf: VideoFile) -> str:
        import hashlib

        h = hashlib.sha1(
            f"{vf.path}|{vf.size}|{int(vf.mtime)}".encode("utf-8", "ignore")
        ).hexdigest()[:16]
        return os.path.join(self.temp_dir, "frames", h)


class ComparisonMethod:
    """Base class for the nine comparison methods.

    Subclasses override :meth:`prepare` (optional, to compute a per-file
    signature) and :meth:`compare` (required, to decide if two files match).
    """

    method_id: MethodId
    #: Whether this method must run pairwise after cheaper bucketing.
    expensive: bool = False
    #: Whether this method requires ffprobe/ffmpeg/fpcalc to be present.
    needs_tools: bool = False

    def available(self, ctx: MethodContext) -> bool:
        """Whether this method can actually run in the current environment."""
        return True

    def prepare(self, vf: VideoFile, ctx: MethodContext) -> None:
        """Compute and cache any per-file signature.  Default: no-op."""
        return None

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        """Return evidence if ``a`` and ``b`` match, else ``None``."""
        raise NotImplementedError
