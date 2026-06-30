"""Core data models shared between the engine and the GUI.

These dataclasses are intentionally free of any Qt or GUI dependency so the
engine can be unit-tested and reused in headless contexts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ScanMode(str, Enum):
    """The three high-level scan presets exposed in the UI."""

    EASY = "easy"
    MEDIUM = "medium"
    ROBUST = "robust"
    CUSTOM = "custom"


class MatchLogic(str, Enum):
    """How results from individual methods are combined for a pair."""

    ANY = "any"  # a pair matches if ANY enabled method agrees
    ALL = "all"  # a pair matches only if ALL enabled methods agree


class KeepRule(str, Enum):
    """Which file to protect (keep) in each duplicate group."""

    HIGHEST_RESOLUTION = "highest_resolution"
    LARGEST_SIZE = "largest_size"
    LONGEST_DURATION = "longest_duration"
    NEWEST = "newest"
    OLDEST = "oldest"
    MANUAL = "manual"


class DeleteMode(str, Enum):
    """How selected files are removed."""

    RECYCLE_BIN = "recycle_bin"
    QUARANTINE = "quarantine"
    PERMANENT = "permanent"


class MethodId(str, Enum):
    """Stable identifiers for the comparison methods (M1-M9).

    M4 (ffprobe metadata matching) was removed; the identifier is intentionally
    not reused.
    """

    SIZE = "size"  # M1
    SHA256 = "sha256"  # M2
    PARTIAL_HASH = "partial_hash"  # M3
    PHASH = "phash"  # M5
    SSIM = "ssim"  # M6
    PSNR = "psnr"  # M7
    VMAF = "vmaf"  # M8
    AUDIO = "audio"  # M9


# Human-friendly labels used by the GUI and help text.
METHOD_LABELS: dict[MethodId, str] = {
    MethodId.SIZE: "M1 - File size",
    MethodId.SHA256: "M2 - SHA-256 full hash",
    MethodId.PARTIAL_HASH: "M3 - Partial/quick hash",
    MethodId.PHASH: "M5 - Perceptual hash",
    MethodId.SSIM: "M6 - SSIM",
    MethodId.PSNR: "M7 - PSNR",
    MethodId.VMAF: "M8 - VMAF",
    MethodId.AUDIO: "M9 - Audio fingerprint",
}


@dataclass
class MediaInfo:
    """Container/stream metadata extracted via ffprobe.

    All fields are optional because corrupt or exotic files may be missing
    some streams.  ``ok`` indicates whether ffprobe produced usable output.
    """

    duration: Optional[float] = None  # seconds
    width: Optional[int] = None
    height: Optional[int] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    bitrate: Optional[int] = None  # bits per second
    fps: Optional[float] = None
    audio_channels: Optional[int] = None
    has_video: bool = False
    has_audio: bool = False
    ok: bool = False

    @property
    def resolution(self) -> Optional[tuple[int, int]]:
        if self.width and self.height:
            return (self.width, self.height)
        return None

    @property
    def pixels(self) -> int:
        """Total pixel count, useful for the 'highest resolution' keep rule."""
        if self.width and self.height:
            return self.width * self.height
        return 0


@dataclass
class VideoFile:
    """A single discovered video file plus all cached signatures.

    Signatures (hashes, perceptual hashes, fingerprints) are filled in lazily
    by the engine and cached on disk keyed by ``(path, size, mtime)``.
    """

    path: str
    size: int
    mtime: float
    ctime: float

    # Lazily-computed signatures.
    info: Optional[MediaInfo] = None
    sha256: Optional[str] = None
    partial_hash: Optional[str] = None
    phashes: Optional[list[str]] = None  # hex perceptual hashes per sampled frame
    audio_fingerprint: Optional[str] = None
    audio_fp_duration: Optional[float] = None

    thumbnail_path: Optional[str] = None
    error: Optional[str] = None  # populated if the file could not be processed

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)

    @property
    def key(self) -> tuple[str, int, int]:
        """Cache key: path + size + integer mtime."""
        return (self.path, self.size, int(self.mtime))


@dataclass
class MatchEvidence:
    """Why two files were considered a match by a single method."""

    method: MethodId
    score: float  # normalized 0..1 similarity (1.0 == identical)
    detail: str = ""


@dataclass
class DuplicateGroup:
    """A cluster of files detected as the same/similar content."""

    files: list[VideoFile] = field(default_factory=list)
    # path -> list of evidence entries that linked it into the group.
    evidence: dict[str, list[MatchEvidence]] = field(default_factory=dict)
    keep_path: Optional[str] = None  # path the app recommends keeping

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def reclaimable(self) -> int:
        """Bytes that could be freed if all but the kept file were deleted."""
        if not self.files:
            return 0
        keep = self.keep_path or (self.files[0].path if self.files else None)
        return sum(f.size for f in self.files if f.path != keep)

    def methods_for(self, path: str) -> list[MethodId]:
        seen: list[MethodId] = []
        for ev in self.evidence.get(path, []):
            if ev.method not in seen:
                seen.append(ev.method)
        return seen


@dataclass
class DeletionResult:
    """Outcome of a single file deletion."""

    path: str
    success: bool
    mode: DeleteMode
    error: Optional[str] = None
    destination: Optional[str] = None  # for quarantine moves
