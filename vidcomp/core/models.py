"""Typed dataclasses shared across the engine and the GUI.

All models are intentionally framework-free (no Qt imports) so the engine and
the test-suite can use them without bringing PySide6 into scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class VideoFile:
    """A discovered video file on disk.

    Equality is on the canonicalised path so we can de-dup the scanner output.
    """

    path: str
    size: int
    mtime: float
    ctime: float

    @property
    def as_path(self) -> Path:
        return Path(self.path)

    @property
    def name(self) -> str:
        return self.as_path.name

    @property
    def parent(self) -> str:
        return str(self.as_path.parent)


@dataclass
class MediaMetadata:
    """Container-level + first-video-stream + first-audio-stream metadata.

    Any field may be ``None`` if ffprobe could not determine it.  We keep the
    raw ffprobe JSON around for debugging/future use.
    """

    duration_sec: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    video_codec: Optional[str] = None
    bit_rate: Optional[int] = None
    fps: Optional[float] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[int] = None
    audio_sample_rate: Optional[int] = None
    has_video: bool = False
    has_audio: bool = False
    raw_json: Optional[str] = None

    @property
    def resolution(self) -> Optional[Tuple[int, int]]:
        if self.width and self.height:
            return (self.width, self.height)
        return None

    @property
    def resolution_str(self) -> str:
        if self.resolution:
            return f"{self.width}x{self.height}"
        return "?"


@dataclass
class MatchEvidence:
    """A single comparison method's verdict for an ordered pair of files."""

    method_id: str
    matched: bool
    score: float                       # method-specific (0..1, 0..100, dB, distance)
    detail: Optional[str] = None
    abstain: bool = False              # True ⇒ method couldn't decide (missing sig, error)


@dataclass
class PairResult:
    """All evidence for an unordered pair of files plus the final verdict."""

    path_a: str
    path_b: str
    evidences: List[MatchEvidence] = field(default_factory=list)
    matched: bool = False              # final decision after ANY/ALL combination

    def methods_that_matched(self) -> List[str]:
        return [e.method_id for e in self.evidences if e.matched]


@dataclass
class DuplicateGroup:
    """A cluster of files that the engine considers duplicates / similar.

    ``keeper_path`` is the file selected by the active keep-rule.  ``files``
    are guaranteed to be at least two and to all live in the same equivalence
    class produced by union-find over agreeing pairs.
    """

    group_id: int
    files: List[VideoFile]
    keeper_path: Optional[str] = None
    pair_scores: Dict[Tuple[str, str], PairResult] = field(default_factory=dict)

    def reclaimable_bytes(self) -> int:
        """Sum of sizes for every non-keeper file."""
        return sum(f.size for f in self.files if f.path != self.keeper_path)

    def matched_methods_for(self, path: str) -> List[str]:
        """Methods that ever flagged the given file vs *any* other file in this group."""
        seen: set[str] = set()
        for (a, b), pr in self.pair_scores.items():
            if path in (a, b):
                seen.update(pr.methods_that_matched())
        return sorted(seen)


@dataclass
class ScanProgress:
    """Progress payload pushed from the scan worker to the UI."""

    stage: str                         # human-readable label
    current: int = 0
    total: int = 0
    current_file: str = ""
    elapsed_sec: float = 0.0
    eta_sec: float = 0.0
    skipped: int = 0
    note: str = ""

    @property
    def fraction(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(1.0, self.current / self.total)


@dataclass
class DeletionResult:
    """Outcome of attempting to delete one file."""

    path: str
    ok: bool
    error: Optional[str] = None
    target: Optional[str] = None       # quarantine destination, etc.


@dataclass
class DeletionReport:
    """Aggregate report returned by :class:`vidcomp.core.deletion`."""

    mode: str
    results: List[DeletionResult] = field(default_factory=list)
    bytes_reclaimed: int = 0

    @property
    def succeeded(self) -> List[DeletionResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> List[DeletionResult]:
        return [r for r in self.results if not r.ok]


@dataclass
class ToolStatus:
    """Result of probing for an external CLI tool."""

    name: str
    path: Optional[str]
    version: Optional[str] = None
    available: bool = False
    error: Optional[str] = None

    @classmethod
    def missing(cls, name: str, error: str = "not found on PATH") -> "ToolStatus":
        return cls(name=name, path=None, version=None, available=False, error=error)


@dataclass
class ToolsStatus:
    """Bundle of statuses for every external tool VidComp may use."""

    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    fpcalc: ToolStatus
    libvmaf: bool = False

    @property
    def required_ok(self) -> bool:
        return self.ffmpeg.available and self.ffprobe.available

    @property
    def missing_required(self) -> List[str]:
        return [t.name for t in (self.ffmpeg, self.ffprobe) if not t.available]

    @property
    def missing_optional(self) -> List[str]:
        missing: List[str] = []
        if not self.fpcalc.available:
            missing.append(self.fpcalc.name)
        if not self.libvmaf:
            missing.append("libvmaf (ffmpeg)")
        return missing
