"""Platform-isolated wrappers around external media tools.

All interaction with ``ffmpeg``, ``ffprobe`` and ``fpcalc`` (Chromaprint) lives
here so the rest of the engine and the GUI never touch ``subprocess`` directly.
Porting VidComp to another OS later should only require changes in this module.

On Windows we pass ``CREATE_NO_WINDOW`` so spawning tools does not flash console
windows.  Every call has a timeout and degrades gracefully when a tool is
missing or a file is unreadable.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional

from .models import MediaInfo

log = logging.getLogger("vidcomp.media")

# Hide console windows for child processes on Windows.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class ToolStatus:
    """Availability of an external tool."""

    name: str
    path: Optional[str]
    available: bool
    has_vmaf: bool = False  # only meaningful for ffmpeg


def _run(
    args: list[str],
    timeout: float = 60.0,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run an external command with no console window and a timeout."""
    log.debug("exec: %s (timeout=%.1fs)", _shellish(args), timeout)
    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
            timeout=timeout,
            check=False,
        )
        log.debug(
            "exec rc=%s stdout=%dB stderr=%dB (%s)",
            cp.returncode,
            len(cp.stdout) if cp.stdout else 0,
            len(cp.stderr) if cp.stderr else 0,
            os.path.basename(args[0]) if args else "?",
        )
        return cp
    except subprocess.TimeoutExpired as exc:
        log.warning("exec TIMEOUT after %.1fs: %s", timeout, _shellish(args))
        raise
    except FileNotFoundError as exc:
        log.warning("exec NOT FOUND: %s (%s)", args[0] if args else "?", exc)
        raise


def _shellish(args: list[str]) -> str:
    """Shell-ish single-line representation of an arg list for logs."""
    out = []
    for a in args:
        s = str(a)
        out.append(f'"{s}"' if " " in s else s)
    return " ".join(out)


def find_tool(name: str, extra_paths: Optional[list[str]] = None) -> Optional[str]:
    """Locate an executable on PATH (or a few common install locations)."""
    found = shutil.which(name)
    if found:
        log.debug("find_tool: %s -> %s (PATH)", name, found)
        return found
    # A handful of common Windows install locations as a convenience.
    candidates: list[str] = []
    if sys.platform == "win32":
        exe = name if name.lower().endswith(".exe") else name + ".exe"
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            if base:
                candidates.append(os.path.join(base, "ffmpeg", "bin", exe))
                candidates.append(os.path.join(base, exe))
    for c in (extra_paths or []) + candidates:
        if c and os.path.isfile(c):
            log.debug("find_tool: %s -> %s (candidate)", name, c)
            return c
    log.debug("find_tool: %s NOT FOUND (PATH=%s)", name, os.environ.get("PATH", "")[:200])
    return None


class MediaTools:
    """Resolves and caches the locations/capabilities of external tools."""

    def __init__(self) -> None:
        log.debug("Resolving external media tools...")
        self.ffmpeg = find_tool("ffmpeg")
        self.ffprobe = find_tool("ffprobe")
        self.fpcalc = find_tool("fpcalc")
        self._has_vmaf: Optional[bool] = None
        log.info(
            "MediaTools resolved: ffmpeg=%s ffprobe=%s fpcalc=%s",
            self.ffmpeg or "MISSING",
            self.ffprobe or "MISSING",
            self.fpcalc or "MISSING",
        )

    # --- availability ------------------------------------------------------
    @property
    def has_ffmpeg(self) -> bool:
        return self.ffmpeg is not None

    @property
    def has_ffprobe(self) -> bool:
        return self.ffprobe is not None

    @property
    def has_fpcalc(self) -> bool:
        return self.fpcalc is not None

    def has_vmaf(self) -> bool:
        """True if the resolved ffmpeg build exposes the libvmaf filter."""
        if self._has_vmaf is not None:
            return self._has_vmaf
        self._has_vmaf = False
        if not self.ffmpeg:
            return False
        try:
            cp = _run([self.ffmpeg, "-hide_banner", "-filters"], timeout=20)
            out = (cp.stdout or b"").decode("utf-8", "ignore")
            self._has_vmaf = "libvmaf" in out
        except Exception as exc:  # pragma: no cover - environment dependent
            log.debug("vmaf probe failed: %s", exc)
        return self._has_vmaf

    def status(self) -> list[ToolStatus]:
        return [
            ToolStatus("ffmpeg", self.ffmpeg, self.has_ffmpeg, self.has_vmaf()),
            ToolStatus("ffprobe", self.ffprobe, self.has_ffprobe),
            ToolStatus("fpcalc", self.fpcalc, self.has_fpcalc),
        ]

    # --- ffprobe metadata --------------------------------------------------
    def probe(self, path: str, timeout: float = 30.0) -> MediaInfo:
        """Extract container/stream metadata for a file via ffprobe."""
        info = MediaInfo()
        if not self.ffprobe:
            log.debug("probe skipped (no ffprobe): %s", path)
            return info
        log.debug("probe: %s", path)
        try:
            cp = _run(
                [
                    self.ffprobe, "-v", "error", "-print_format", "json",
                    "-show_format", "-show_streams", path,
                ],
                timeout=timeout,
            )
            if cp.returncode != 0 or not cp.stdout:
                return info
            data = json.loads(cp.stdout.decode("utf-8", "ignore"))
        except Exception as exc:
            log.debug("ffprobe failed for %s: %s", path, exc)
            return info

        fmt = data.get("format", {})
        try:
            if fmt.get("duration"):
                info.duration = float(fmt["duration"])
            if fmt.get("bit_rate"):
                info.bitrate = int(fmt["bit_rate"])
        except (TypeError, ValueError):
            pass

        for stream in data.get("streams", []):
            ctype = stream.get("codec_type")
            if ctype == "video" and not info.has_video:
                info.has_video = True
                info.video_codec = stream.get("codec_name")
                info.width = _as_int(stream.get("width"))
                info.height = _as_int(stream.get("height"))
                info.fps = _parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
                if info.duration is None and stream.get("duration"):
                    info.duration = _as_float(stream.get("duration"))
            elif ctype == "audio" and not info.has_audio:
                info.has_audio = True
                info.audio_codec = stream.get("codec_name")
                info.audio_channels = _as_int(stream.get("channels"))

        info.ok = info.has_video or info.has_audio or info.duration is not None
        log.debug(
            "probe -> ok=%s dur=%s res=%sx%s codec=%s fps=%s",
            info.ok, info.duration, info.width, info.height, info.video_codec, info.fps,
        )
        return info

    # --- frame extraction --------------------------------------------------
    def extract_frames(
        self,
        path: str,
        count: int,
        duration: Optional[float],
        out_dir: str,
        size: int = 256,
        timeout: float = 120.0,
    ) -> list[str]:
        """Extract ``count`` evenly-spaced frames as JPEGs into ``out_dir``.

        Returns the list of frame file paths actually produced (may be shorter
        than ``count`` for short/odd files).
        """
        if not self.ffmpeg or count <= 0:
            return []
        os.makedirs(out_dir, exist_ok=True)
        produced: list[str] = []

        # When we know the duration, grab frames at fixed timestamps; this is
        # robust for files where the 'select' filter would be unpredictable.
        if duration and duration > 0:
            # Avoid the very first/last instants which are often black.
            margin = min(1.0, duration * 0.05)
            usable = max(duration - 2 * margin, 0.0)
            for i in range(count):
                frac = (i + 0.5) / count
                ts = margin + usable * frac
                out = os.path.join(out_dir, f"frame_{i:03d}.jpg")
                try:
                    cp = _run(
                        [
                            self.ffmpeg, "-hide_banner", "-loglevel", "error",
                            "-ss", f"{ts:.3f}", "-i", path, "-frames:v", "1",
                            "-vf", f"scale={size}:-1", "-q:v", "3", "-y", out,
                        ],
                        timeout=timeout,
                    )
                    if cp.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
                        produced.append(out)
                except Exception as exc:
                    log.debug("frame extract failed (%s @ %.2fs): %s", path, ts, exc)
            return produced

        # Unknown duration: ask ffmpeg for the first N frames at a low fps.
        pattern = os.path.join(out_dir, "frame_%03d.jpg")
        try:
            _run(
                [
                    self.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", path,
                    "-vf", f"fps=1,scale={size}:-1", "-frames:v", str(count),
                    "-q:v", "3", "-y", pattern,
                ],
                timeout=timeout,
            )
        except Exception as exc:
            log.debug("sequential frame extract failed (%s): %s", path, exc)
        for i in range(1, count + 1):
            out = os.path.join(out_dir, f"frame_{i:03d}.jpg")
            if os.path.isfile(out) and os.path.getsize(out) > 0:
                produced.append(out)
        return produced

    def extract_thumbnail(
        self,
        path: str,
        out_path: str,
        duration: Optional[float],
        size: int = 320,
        timeout: float = 60.0,
    ) -> Optional[str]:
        """Extract a single representative frame to ``out_path`` (JPEG)."""
        if not self.ffmpeg:
            return None
        ts = 1.0
        if duration and duration > 0:
            ts = max(0.0, min(duration * 0.25, duration - 0.1))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        try:
            cp = _run(
                [
                    self.ffmpeg, "-hide_banner", "-loglevel", "error",
                    "-ss", f"{ts:.3f}", "-i", path, "-frames:v", "1",
                    "-vf", f"scale={size}:-1", "-q:v", "3", "-y", out_path,
                ],
                timeout=timeout,
            )
            if cp.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return out_path
        except Exception as exc:
            log.debug("thumbnail extract failed (%s): %s", path, exc)
        return None

    # --- SSIM / PSNR via lavfi --------------------------------------------
    def ssim_psnr(
        self,
        ref: str,
        cmp: str,
        timeout: float = 180.0,
    ) -> tuple[Optional[float], Optional[float]]:
        """Compute average SSIM (0..1) and PSNR (dB) between two videos.

        Both inputs are scaled to a common small resolution and compared frame
        for frame.  Returns ``(None, None)`` if ffmpeg is missing or fails.
        """
        if not self.ffmpeg:
            return (None, None)
        # ffmpeg's ssim/psnr filters each print their own summary to stderr, so
        # we run them separately for reliable parsing. Both inputs are scaled to
        # a common small resolution and a low fps to keep the comparison fast.
        ssim = self._single_metric(ref, cmp, "ssim", timeout)
        psnr = self._single_metric(ref, cmp, "psnr", timeout)
        return (ssim, psnr)

    def _single_metric(
        self, ref: str, cmp: str, metric: str, timeout: float
    ) -> Optional[float]:
        flt = (
            f"[0:v]scale=320:180:flags=bilinear,setsar=1,fps=2[a];"
            f"[1:v]scale=320:180:flags=bilinear,setsar=1,fps=2[b];"
            f"[a][b]{metric}"
        )
        try:
            cp = _run(
                [
                    self.ffmpeg, "-hide_banner", "-loglevel", "info",
                    "-i", ref, "-i", cmp,
                    "-filter_complex", flt, "-an", "-f", "null", os.devnull,
                ],
                timeout=timeout,
            )
            err = (cp.stderr or b"").decode("utf-8", "ignore")
            return _parse_metric(err, metric)
        except Exception as exc:
            log.debug("%s failed (%s vs %s): %s", metric, ref, cmp, exc)
            return None

    # --- VMAF --------------------------------------------------------------
    def vmaf(self, ref: str, cmp: str, timeout: float = 300.0) -> Optional[float]:
        """Compute the mean VMAF score (0..100) if libvmaf is available."""
        if not self.ffmpeg or not self.has_vmaf():
            return None
        flt = (
            "[0:v]scale=640:360:flags=bilinear,setsar=1,fps=5[a];"
            "[1:v]scale=640:360:flags=bilinear,setsar=1,fps=5[b];"
            "[b][a]libvmaf=log_fmt=json"
        )
        with tempfile.TemporaryDirectory(prefix="vidcomp_vmaf_") as tmp:
            log_path = os.path.join(tmp, "vmaf.json")
            flt_logged = flt.replace(
                "libvmaf=log_fmt=json",
                f"libvmaf=log_fmt=json:log_path={log_path.replace(os.sep, '/')}",
            )
            try:
                _run(
                    [
                        self.ffmpeg, "-hide_banner", "-loglevel", "error",
                        "-i", cmp, "-i", ref,
                        "-filter_complex", flt_logged, "-an", "-f", "null", os.devnull,
                    ],
                    timeout=timeout,
                )
                if os.path.isfile(log_path):
                    with open(log_path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    pooled = data.get("pooled_metrics", {}).get("vmaf", {})
                    if "mean" in pooled:
                        return float(pooled["mean"])
                    if data.get("frames"):
                        vals = [f["metrics"]["vmaf"] for f in data["frames"] if "metrics" in f]
                        if vals:
                            return sum(vals) / len(vals)
            except Exception as exc:
                log.debug("vmaf failed (%s vs %s): %s", ref, cmp, exc)
        return None

    # --- Chromaprint audio fingerprint ------------------------------------
    def fingerprint(self, path: str, timeout: float = 120.0) -> tuple[Optional[str], Optional[float]]:
        """Return (raw fingerprint, duration) from fpcalc, or (None, None).

        The raw fingerprint is a comma-separated list of 32-bit integers, which
        is what we need for bit-level similarity comparison (the default
        base64-compressed form cannot be compared directly).
        """
        if not self.fpcalc:
            return (None, None)
        try:
            cp = _run([self.fpcalc, "-raw", "-json", path], timeout=timeout)
            if cp.returncode == 0 and cp.stdout:
                data = json.loads(cp.stdout.decode("utf-8", "ignore"))
                fp = data.get("fingerprint")
                if isinstance(fp, list):
                    fp = ",".join(str(int(x)) for x in fp)
                return (fp, _as_float(data.get("duration")))
        except Exception as exc:
            log.debug("fpcalc failed (%s): %s", path, exc)
        return (None, None)


# --- parsing helpers -------------------------------------------------------

def _as_int(v: object) -> Optional[int]:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(v: object) -> Optional[float]:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_fps(rate: Optional[str]) -> Optional[float]:
    if not rate:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


def _parse_metric(stderr: str, metric: str) -> Optional[float]:
    """Parse the average SSIM/PSNR value from ffmpeg's stderr output."""
    import re

    if metric == "ssim":
        # e.g. "SSIM ... All:0.987654 (19.1)"
        m = re.search(r"SSIM.*?All:([0-9.]+)", stderr)
        if m:
            return _as_float(m.group(1))
    elif metric == "psnr":
        # e.g. "PSNR ... average:34.56 ..."
        m = re.search(r"PSNR.*?average:([0-9.]+|inf)", stderr)
        if m:
            val = m.group(1)
            if val == "inf":
                return float("inf")
            return _as_float(val)
    return None
