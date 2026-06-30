# VidComp - Video Duplicate / Similarity Finder

VidComp is a GUI desktop app (PySide6) that recursively scans a folder for
**duplicate and visually similar videos by their content**, regardless of
filename, and lets you review and safely delete the extras.

It uses a tiered, escalating comparison pipeline so that cheap filters run first
and expensive metrics only run on surviving candidates:

```
size  ->  partial hash  ->  SHA-256  ->  perceptual hash  ->  SSIM / PSNR / VMAF / audio
```

---

## Features

- Recursive scan of a folder and all subfolders, matching by content.
- Three scan modes: **Easy**, **Medium**, **Robust**.
- Nine pluggable comparison methods (M1-M9), each individually toggleable in an
  **Advanced** panel with tunable thresholds and ANY/ALL match logic.
- Grouped results with thumbnails, full metadata, "matched by" evidence and a
  recommended *keep* file per group.
- Auto-select duplicates by a configurable keep rule, always preserving at least
  one file per group.
- Three delete modes: Recycle Bin, quarantine folder, permanent.
- On-disk SQLite cache for hashes/metadata and a bounded thumbnail cache, so
  re-scans are fast.
- Responsive UI (work runs in background threads) with progress, ETA and Cancel.
- Light/dark theme.

---

## Prerequisites

### 1. Python

Python **3.10+** (tested on 3.13).

### 2. External tools (on PATH)

These are command-line programs, **not** pip packages:

| Tool | Used for | Where to get it |
|------|----------|-----------------|
| `ffmpeg` + `ffprobe` | metadata, frame extraction, SSIM/PSNR/VMAF | https://www.gyan.dev/ffmpeg/builds/ or https://github.com/BtbN/FFmpeg-Builds/releases |
| `fpcalc` (Chromaprint) | audio fingerprinting (M9) | https://acoustid.org/chromaprint |

On Windows: unzip each, then add the folder containing the `.exe` files to your
**PATH** environment variable, and restart your terminal / VidComp.

- **Easy** mode works with just `ffmpeg` + `ffprobe`.
- **M8 VMAF** needs an ffmpeg build compiled with `libvmaf` (the gyan.dev
  "full" builds include it). If absent, VMAF is disabled automatically.
- **M9 Audio** needs `fpcalc`. If absent, audio matching is disabled
  automatically.

VidComp detects these at startup and shows a friendly setup dialog if any are
missing - it will still launch.

---

## Installation

```bash
# (recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

## Running

```bash
python main.py
```

---

## How the scan modes work (plain language)

- **Easy (fast):** Groups files by size, then confirms exact copies with a
  quick head+tail hash and a full SHA-256. Great for finding literal
  duplicate files with different names.

- **Medium (balanced):** Everything in Easy, plus **perceptual hashing**: it
  samples frames at intervals, fingerprints each frame, and matches videos whose
  frame hashes are within a Hamming-distance threshold. Catches re-encoded or
  resized copies that are not byte-identical.

- **Robust (thorough, slow):** Everything in Medium, plus **SSIM** and **PSNR**
  frame comparisons, optional **VMAF**, and **audio fingerprinting**. These
  expensive checks only run on candidate pairs that survive the cheaper filters.

## The methods (M1-M9)

> **Note:** M4 (ffprobe metadata matching) was removed because it produced too
> many false positives in practice — two unrelated clips that happened to share
> a duration / resolution / codec were being flagged as duplicates. Real
> re-encodes are caught by M5–M8 instead. The M4 slot is intentionally left
> blank below; identifiers are not renumbered so existing logs / caches / tests
> stay consistent.

| ID | Method | What it does |
|----|--------|--------------|
| M1 | File size | Instant pre-filter; groups equal-sized files. |
| M2 | SHA-256 | Confirms byte-identical duplicates. |
| M3 | Partial hash | Hashes first+last N bytes for a fast pre-check. |
| ~~M4~~ | ~~Metadata~~ | Removed (unreliable — see note above). |
| M5 | Perceptual hash | pHash of sampled frames; Hamming-distance threshold. |
| M6 | SSIM | Structural similarity of aligned frames (0-1). |
| M7 | PSNR | Peak signal-to-noise ratio (dB). |
| M8 | VMAF | Netflix perceptual quality metric (needs libvmaf). |
| M9 | Audio fingerprint | Chromaprint similarity of the audio track. |

**Match logic:** *ANY* flags a pair when a single enabled method agrees (more
results); *ALL* requires every enabled method to agree (stricter).

## Keep rules & deletion

The keep rule selects the protected file in each group: highest resolution,
largest size, longest duration, newest, oldest, or manual. "Select duplicates"
checks everything except the kept file. VidComp **never** deletes every file in
a group.

Delete modes (Settings): Recycle Bin (reversible, via `send2trash`), move to a
quarantine folder, or permanent delete (with an extra confirmation).

---

## Caching

Hashes, perceptual hashes, metadata and audio fingerprints are cached in a
SQLite database keyed by `(path, size, modified-time)`. Thumbnails are cached as
JPEGs in a size-bounded folder. Editing or replacing a file invalidates its
cache entry automatically. Cache and thumbnail locations and the thumbnail
budget are configurable in Settings.

---

## Project layout

```
vidcomp/
  main.py                  # entry point
  requirements.txt
  README.md
  vidcomp/
    config.py              # AppConfig, ScanOptions, mode presets
    workers.py             # QThread scan worker + thumbnail runnable
    core/
      models.py            # dataclasses + enums
      media.py             # ffmpeg/ffprobe/fpcalc wrappers (platform-isolated)
      cache.py             # SQLite signature cache
      thumbnails.py        # thumbnail extraction + bounded cache
      scanner.py           # recursive discovery
      engine.py            # orchestration + grouping (union-find)
      keep_rules.py        # keep-file selection
      deletion.py          # recycle/quarantine/permanent delete
      utils.py             # formatting helpers
      methods/             # M1-M9, one module each, behind ComparisonMethod
    gui/
      main_window.py
      style.py
      widgets/             # advanced panel, results view, dialogs
  tests/                   # pytest unit tests for the engine
```

---

## Running the tests

```bash
pip install pytest
pytest
```

The tests cover the comparison methods, duplicate-grouping logic, keep-rule
selection and the deletion safety rules using small synthetic inputs (no real
videos or external tools required).

---

## Packaging a standalone Windows .exe (PyInstaller)

A ready-to-use spec (`VidComp.spec`) and a PowerShell wrapper (`build.ps1`) are
included. The build **keeps the console window** (`console=True`) so any
startup error, traceback or `--debug` output is visible immediately.

```powershell
.\build.ps1               # standard build
.\build.ps1 -Clean        # wipe build/ + dist/ first
.\build.ps1 -Clean -Debug # also drop a VidComp-debug.cmd launcher that forces --debug
```

Or directly:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm VidComp.spec
```

Run the result from a terminal so log lines show up live:

```powershell
.\dist\VidComp\VidComp.exe --debug
```

Verbose log output also lands in `%APPDATA%\VidComp\logs\vidcomp.log`
regardless of how the app is launched.

Notes:

- To produce a fully self-contained distribution, drop `ffmpeg.exe`,
  `ffprobe.exe` and `fpcalc.exe` next to `VidComp.spec` *before* building -
  the spec auto-detects and bundles them. Otherwise they need to be on the
  user's PATH.
- If you want the old hidden-console behaviour, edit `VidComp.spec` and set
  `console=False` - but you'll lose the live debug output.

### Debugging tips

- `python main.py --debug` (or `set VIDCOMP_DEBUG=1` then `python main.py`)
  enables DEBUG-level logging both on the console and in the rotating log
  file. The log file lives at `%APPDATA%\VidComp\logs\vidcomp.log`.
- The frozen `VidComp.exe` honours the same `--debug` flag and
  `VIDCOMP_DEBUG=1` environment variable.
- An installed global excepthook routes any unhandled exception (main or
  worker thread) into the same log, so crashes are never silent.

---

## Library choices / notes

- **Perceptual hashing (M5)** is implemented in-process using only `opencv-python`
  + `numpy` (both already required for frame sampling). The upstream `phash`
  PyPI package wraps a C++ library that needs CMake/MSVC and famously fails
  to install on Windows; the older recipe based on `imagehash` + `scipy` also
  trips up minimal installs. VidComp ships its own 64-bit pHash so neither is
  needed. If `imagehash` happens to be installed it is used as a drop-in
  accelerator, otherwise the built-in path runs automatically.
- **Metadata matching (M4) was removed.** Comparing duration / resolution /
  codec / bitrate cannot reliably distinguish two unrelated clips that happen
  to share those attributes (e.g. two different 1080p H.264 episodes of the
  same length), and even tightened gates produced false positives. The
  ffprobe-derived `MediaInfo` is still produced and cached for the methods
  that genuinely need it (M5 pHash sanity guards, SSIM/PSNR/VMAF). Saved
  configs with `"metadata"` in `enabled_methods` are loaded with that entry
  silently dropped.
- **SSIM/PSNR/VMAF** use ffmpeg's `lavfi` filters (no extra Python deps).
  `scikit-image` is listed as an optional SSIM fallback.
- **Audio fingerprinting** uses `fpcalc` (Chromaprint) directly for raw
  fingerprints so similarity can be computed via bit-error-rate.
- All external-tool access is isolated in `vidcomp/core/media.py` so other
  platforms can be added later without touching the GUI.
