"""External-tool detection and ffmpeg/ffprobe/fpcalc wrappers.

Every function that shells out:
    * Honours an optional :class:`threading.Event` *cancel_event* so a scan can
      be cancelled within seconds rather than waiting for ffmpeg to finish.
    * Captures stderr separately so callers can surface useful errors.
    * Times out generously (so a hung subprocess can't deadlock the GUI).

The module intentionally has no Qt dependency — it is the "platform isolation"
layer the prompt asks for.  Today everything is ffmpeg/ffprobe/fpcalc which work
on Windows, but a future port would only need to swap implementations here.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .models import MediaMetadata, ToolStatus, ToolsStatus

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subprocess flags — silence the console window on Windows when packaged.
# ---------------------------------------------------------------------------
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class _ToolPaths:
    ffmpeg: Optional[str] = None
    ffprobe: Optional[str] = None
    fpcalc: Optional[str] = None


_paths = _ToolPaths()
_libvmaf_available: Optional[bool] = None
_detection_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------
def _which(name: str) -> Optional[str]:
    return shutil.which(name) or shutil.which(name + ".exe")


def _run_capture(
    argv: List[str],
    timeout: float = 15.0,
) -> Tuple[int, str, str]:
    """Run a quick command, return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)


def _probe_tool_version(path: str, args: List[str] = None) -> Optional[str]:
    args = args or ["-version"]
    rc, out, err = _run_capture([path, *args], timeout=10.0)
    text = (out or "") + (err or "")
    # First line typically contains the version.
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first or None


def detect_tools(force: bool = False) -> ToolsStatus:
    """Probe ``ffmpeg``, ``ffprobe``, ``fpcalc`` on PATH; also detect libvmaf."""
    global _libvmaf_available
    with _detection_lock:
        if not force and _paths.ffmpeg and _paths.ffprobe:
            pass  # use cached
        _paths.ffmpeg = _which("ffmpeg")
        _paths.ffprobe = _which("ffprobe")
        _paths.fpcalc = _which("fpcalc")

        def _status(name: str, path: Optional[str]) -> ToolStatus:
            if not path:
                return ToolStatus.missing(name)
            version = _probe_tool_version(path)
            return ToolStatus(name=name, path=path, version=version, available=True)

        ff = _status("ffmpeg", _paths.ffmpeg)
        fp = _status("ffprobe", _paths.ffprobe)
        ac = _status("fpcalc", _paths.fpcalc)

        libvmaf = False
        if _paths.ffmpeg:
            rc, out, _err = _run_capture([_paths.ffmpeg, "-hide_banner", "-filters"], timeout=10.0)
            if rc == 0 and "libvmaf" in out.lower():
                libvmaf = True
        _libvmaf_available = libvmaf

        return ToolsStatus(ffmpeg=ff, ffprobe=fp, fpcalc=ac, libvmaf=libvmaf)


def ffmpeg_path() -> str:
    if not _paths.ffmpeg:
        detect_tools()
    if not _paths.ffmpeg:
        raise FileNotFoundError("ffmpeg not found on PATH")
    return _paths.ffmpeg


def ffprobe_path() -> str:
    if not _paths.ffprobe:
        detect_tools()
    if not _paths.ffprobe:
        raise FileNotFoundError("ffprobe not found on PATH")
    return _paths.ffprobe


def fpcalc_path() -> Optional[str]:
    if not _paths.fpcalc:
        detect_tools()
    return _paths.fpcalc


def has_libvmaf() -> bool:
    if _libvmaf_available is None:
        detect_tools()
    return bool(_libvmaf_available)


def has_fpcalc() -> bool:
    return fpcalc_path() is not None


# ---------------------------------------------------------------------------
# Cancellable subprocess
# ---------------------------------------------------------------------------
def _run_cancellable(
    argv: List[str],
    cancel_event: Optional[threading.Event] = None,
    timeout: float = 600.0,
    cwd: Optional[str] = None,
) -> Tuple[int, str, str]:
    """Run a subprocess, polling *cancel_event* every 100 ms.

    On cancel the process is terminated (then killed if needed) and we return
    ``(-1, stdout_so_far, stderr_so_far)``.
    """
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)

    start = time.time()
    while True:
        if proc.poll() is not None:
            break
        if cancel_event is not None and cancel_event.is_set():
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
            out, err = proc.communicate()
            return -1, _decode(out), _decode(err)
        if time.time() - start > timeout:
            proc.kill()
            out, err = proc.communicate()
            return -1, _decode(out), _decode(err)
        time.sleep(0.1)

    out, err = proc.communicate()
    return proc.returncode, _decode(out), _decode(err)


def _decode(b: Optional[bytes]) -> str:
    if not b:
        return ""
    try:
        return b.decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Metadata (ffprobe)
# ---------------------------------------------------------------------------
def probe_metadata(
    path: str,
    cancel_event: Optional[threading.Event] = None,
) -> MediaMetadata:
    """Run ffprobe and parse the JSON into a :class:`MediaMetadata`."""
    argv = [
        ffprobe_path(),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    rc, out, err = _run_cancellable(argv, cancel_event=cancel_event, timeout=60.0)
    if rc != 0 or not out.strip():
        raise RuntimeError(f"ffprobe failed for {path}: {err.strip() or 'no output'}")
    return parse_ffprobe_json(out)


def parse_ffprobe_json(text: str) -> MediaMetadata:
    """Parse ffprobe JSON output into a :class:`MediaMetadata`.

    Exposed for unit tests so we don't need a real video on disk.
    """
    data = json.loads(text)
    md = MediaMetadata(raw_json=text)
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []

    duration = fmt.get("duration")
    if duration is not None:
        try:
            md.duration_sec = float(duration)
        except (TypeError, ValueError):
            md.duration_sec = None
    if "bit_rate" in fmt:
        try:
            md.bit_rate = int(fmt["bit_rate"])
        except (TypeError, ValueError):
            md.bit_rate = None

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is not None:
        md.has_video = True
        md.video_codec = video.get("codec_name")
        try:
            md.width = int(video["width"])
            md.height = int(video["height"])
        except (KeyError, TypeError, ValueError):
            pass
        fr = video.get("avg_frame_rate") or video.get("r_frame_rate")
        md.fps = _parse_fraction(fr)
        if md.duration_sec is None and "duration" in video:
            try:
                md.duration_sec = float(video["duration"])
            except (TypeError, ValueError):
                pass
        if md.bit_rate is None and "bit_rate" in video:
            try:
                md.bit_rate = int(video["bit_rate"])
            except (TypeError, ValueError):
                pass

    if audio is not None:
        md.has_audio = True
        md.audio_codec = audio.get("codec_name")
        try:
            md.audio_channels = int(audio.get("channels", 0)) or None
        except (TypeError, ValueError):
            pass
        try:
            md.audio_sample_rate = int(audio.get("sample_rate", 0)) or None
        except (TypeError, ValueError):
            pass

    return md


def _parse_fraction(value: Optional[str]) -> Optional[float]:
    if not value or value == "0/0":
        return None
    if "/" in value:
        try:
            num, denom = value.split("/", 1)
            num_f = float(num)
            denom_f = float(denom)
            if denom_f == 0:
                return None
            return num_f / denom_f
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------
def extract_frames_to_dir(
    path: str,
    timestamps_sec: List[float],
    out_dir: Path,
    cancel_event: Optional[threading.Event] = None,
    size: Tuple[int, int] = (320, 180),
) -> List[Path]:
    """Extract one frame per timestamp into *out_dir* as PNG.

    Returns the list of paths actually produced (some timestamps may fail on
    very short files); never raises for an individual failure.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_files: List[Path] = []
    width, height = size
    for i, ts in enumerate(timestamps_sec):
        if cancel_event is not None and cancel_event.is_set():
            break
        target = out_dir / f"frame_{i:03d}.png"
        argv = [
            ffmpeg_path(),
            "-y",
            "-ss", f"{max(0.0, ts):.3f}",
            "-i", path,
            "-frames:v", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            "-q:v", "3",
            str(target),
        ]
        rc, _out, err = _run_cancellable(argv, cancel_event=cancel_event, timeout=60.0)
        if rc == 0 and target.exists():
            out_files.append(target)
        else:
            LOG.debug("frame extract failed for %s @ %.3fs: %s", path, ts, err.strip())
    return out_files


def extract_single_frame(
    path: str,
    timestamp_sec: float,
    out_file: Path,
    cancel_event: Optional[threading.Event] = None,
    size: Tuple[int, int] = (320, 180),
) -> bool:
    """Extract one frame to *out_file*; return True on success."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    argv = [
        ffmpeg_path(),
        "-y",
        "-ss", f"{max(0.0, timestamp_sec):.3f}",
        "-i", path,
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
        "-q:v", "3",
        str(out_file),
    ]
    rc, _out, _err = _run_cancellable(argv, cancel_event=cancel_event, timeout=60.0)
    return rc == 0 and out_file.exists()


def compute_uniform_timestamps(duration_sec: float, count: int) -> List[float]:
    """Pick ``count`` timestamps inside ``[0, duration_sec)`` spaced uniformly.

    The first and last frames are skipped to avoid black-screen artefacts.
    """
    if count <= 0:
        return []
    if duration_sec <= 0:
        return [0.0] * count
    # Place samples at i / (count + 1) of duration for inner placement.
    return [duration_sec * (i + 1) / (count + 1) for i in range(count)]


# ---------------------------------------------------------------------------
# SSIM / PSNR / VMAF via ffmpeg lavfi
# ---------------------------------------------------------------------------
_SSIM_RE = re.compile(r"All:\s*([0-9.]+)")
_PSNR_RE = re.compile(r"average:\s*([0-9.]+)")
_VMAF_RE = re.compile(r"VMAF score:\s*([0-9.]+)", re.IGNORECASE)
_VMAF_JSON_RE = re.compile(r'"VMAF score"\s*:\s*([0-9.]+)')


def _common_duration(a_dur: Optional[float], b_dur: Optional[float]) -> Optional[float]:
    if a_dur is None or b_dur is None:
        return None
    d = min(a_dur, b_dur)
    return d if d > 0 else None


def run_ssim(
    path_a: str,
    path_b: str,
    duration_a: Optional[float] = None,
    duration_b: Optional[float] = None,
    target_size: Tuple[int, int] = (320, 180),
    cancel_event: Optional[threading.Event] = None,
) -> Optional[float]:
    """Return SSIM (0..1) between two videos, or ``None`` on failure."""
    dur = _common_duration(duration_a, duration_b)
    width, height = target_size
    vf = (
        f"[0:v]scale={width}:{height},setpts=PTS-STARTPTS[a];"
        f"[1:v]scale={width}:{height},setpts=PTS-STARTPTS[b];"
        f"[a][b]ssim"
    )
    argv = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostats",
        "-i", path_a,
        "-i", path_b,
        "-lavfi", vf,
        "-an",
    ]
    if dur is not None:
        argv += ["-t", f"{dur:.3f}"]
    argv += ["-f", "null", "-"]
    rc, _out, err = _run_cancellable(argv, cancel_event=cancel_event, timeout=600.0)
    if rc != 0:
        return None
    return _last_float(_SSIM_RE.findall(err))


def run_psnr(
    path_a: str,
    path_b: str,
    duration_a: Optional[float] = None,
    duration_b: Optional[float] = None,
    target_size: Tuple[int, int] = (320, 180),
    cancel_event: Optional[threading.Event] = None,
) -> Optional[float]:
    """Return PSNR in dB between two videos, or ``None`` on failure.

    ``inf`` is returned by ffmpeg for identical inputs; we map that to a large
    finite value (200.0) so callers can compare numerically.
    """
    dur = _common_duration(duration_a, duration_b)
    width, height = target_size
    vf = (
        f"[0:v]scale={width}:{height},setpts=PTS-STARTPTS[a];"
        f"[1:v]scale={width}:{height},setpts=PTS-STARTPTS[b];"
        f"[a][b]psnr"
    )
    argv = [
        ffmpeg_path(),
        "-hide_banner",
        "-nostats",
        "-i", path_a,
        "-i", path_b,
        "-lavfi", vf,
        "-an",
    ]
    if dur is not None:
        argv += ["-t", f"{dur:.3f}"]
    argv += ["-f", "null", "-"]
    rc, _out, err = _run_cancellable(argv, cancel_event=cancel_event, timeout=600.0)
    if rc != 0:
        return None
    # ffmpeg prints `PSNR ... average:NN.NN ...` and may print `inf`
    if "average:inf" in err:
        return 200.0
    return _last_float(_PSNR_RE.findall(err))


def run_vmaf(
    path_a: str,
    path_b: str,
    duration_a: Optional[float] = None,
    duration_b: Optional[float] = None,
    target_size: Tuple[int, int] = (320, 180),
    cancel_event: Optional[threading.Event] = None,
) -> Optional[float]:
    """Return VMAF (0..100) between two videos, or ``None`` if unsupported/failed."""
    if not has_libvmaf():
        return None
    dur = _common_duration(duration_a, duration_b)
    width, height = target_size

    # Use a temp log file so we can parse a deterministic JSON output.
    with tempfile.TemporaryDirectory(prefix="vidcomp_vmaf_") as tmp:
        log_path = Path(tmp) / "vmaf.json"
        # ffmpeg parses ":" in filter args; use forward slashes on Windows.
        log_arg = str(log_path).replace("\\", "/")
        vf = (
            f"[0:v]scale={width}:{height},setpts=PTS-STARTPTS[a];"
            f"[1:v]scale={width}:{height},setpts=PTS-STARTPTS[b];"
            f"[a][b]libvmaf=log_fmt=json:log_path={log_arg}"
        )
        argv = [
            ffmpeg_path(),
            "-hide_banner",
            "-nostats",
            "-i", path_a,
            "-i", path_b,
            "-lavfi", vf,
            "-an",
        ]
        if dur is not None:
            argv += ["-t", f"{dur:.3f}"]
        argv += ["-f", "null", "-"]
        rc, _out, err = _run_cancellable(argv, cancel_event=cancel_event, timeout=900.0)
        if rc != 0:
            return None

        if log_path.exists():
            try:
                data = json.loads(log_path.read_text(encoding="utf-8"))
                pooled = data.get("pooled_metrics", {}).get("vmaf", {})
                mean = pooled.get("mean")
                if mean is not None:
                    return float(mean)
            except (OSError, json.JSONDecodeError):
                pass

        # Fall back to scraping stderr.
        m = _VMAF_RE.search(err) or _VMAF_JSON_RE.search(err)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
        return None


def _last_float(values: List[str]) -> Optional[float]:
    if not values:
        return None
    try:
        return float(values[-1])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Chromaprint audio fingerprint
# ---------------------------------------------------------------------------
def audio_fingerprint(
    path: str,
    length_sec: int = 120,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Tuple[int, List[int]]]:
    """Return ``(duration_sec, raw_fingerprint_ints)`` or None on failure/missing tool."""
    fp = fpcalc_path()
    if not fp:
        return None
    argv = [fp, "-raw", "-json", "-length", str(length_sec), path]
    rc, out, _err = _run_cancellable(argv, cancel_event=cancel_event, timeout=180.0)
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    fingerprint = data.get("fingerprint")
    duration = data.get("duration")
    if not isinstance(fingerprint, list) or not fingerprint:
        return None
    try:
        return int(duration or 0), [int(x) for x in fingerprint]
    except (TypeError, ValueError):
        return None


def fingerprint_similarity(fp_a: List[int], fp_b: List[int]) -> float:
    """Sliding-window cross-correlation of two raw Chromaprint fingerprints.

    Returns a similarity in ``[0.0, 1.0]``.  Each fingerprint integer holds 32
    bits; we use bit-wise XOR + popcount and compute ``1 - hamming / total_bits``
    over the best alignment within a bounded window.
    """
    if not fp_a or not fp_b:
        return 0.0
    a = np.asarray(fp_a, dtype=np.uint32)
    b = np.asarray(fp_b, dtype=np.uint32)
    # Bound the offset search to keep this fast for long fingerprints.
    max_offset = min(40, min(len(a), len(b)) - 1)
    best = 0.0
    for offset in range(-max_offset, max_offset + 1):
        if offset >= 0:
            x = a[offset:]
            y = b[: len(x)]
        else:
            y = b[-offset:]
            x = a[: len(y)]
        n = min(len(x), len(y))
        if n < 8:
            continue
        x = x[:n]
        y = y[:n]
        xor = np.bitwise_xor(x, y)
        # popcount on uint32 array via numpy
        bits = _popcount32(xor)
        hamming = int(bits.sum())
        total = n * 32
        sim = 1.0 - hamming / total
        if sim > best:
            best = sim
    return float(best)


def _popcount32(arr: np.ndarray) -> np.ndarray:
    """Vectorised population count for an array of uint32 values."""
    a = arr.astype(np.uint32)
    a = a - ((a >> np.uint32(1)) & np.uint32(0x55555555))
    a = (a & np.uint32(0x33333333)) + ((a >> np.uint32(2)) & np.uint32(0x33333333))
    a = (a + (a >> np.uint32(4))) & np.uint32(0x0F0F0F0F)
    return (a * np.uint32(0x01010101)) >> np.uint32(24)
