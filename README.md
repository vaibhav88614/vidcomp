# VidComp — GUI video duplicate / similarity comparer (Windows)

**VidComp** recursively scans a folder for video files and finds duplicates and
near-duplicates by comparing their **content** (not their filenames). It groups
matching files, shows a thumbnail and full metadata for each, recommends which
file to keep, and lets you safely delete the rest to the Recycle Bin, a
quarantine folder, or permanently.

Built with Python 3.10+, PySide6, OpenCV, imagehash, ffmpeg/ffprobe and
Chromaprint.

---

## Highlights

- **Three scan modes** — *Easy* (fast, exact duplicates), *Medium* (catches
  re-encoded / resized copies via pHash), *Robust* (adds SSIM, PSNR, VMAF, and
  audio fingerprinting).
- **Nine pluggable comparison methods (M1–M9)** with individual toggles and
  per-method thresholds in an Advanced panel.
- **Smart pipeline** — cheap filters (size → hash → metadata) run first; only
  surviving candidate pairs are passed to expensive checks.
- **Cancellable, non-blocking GUI** — all heavy work runs in a worker thread
  with progress + ETA; Cancel always responds within a couple of seconds.
- **Cached** — hashes, perceptual hashes, ffprobe metadata, pair-wise SSIM/PSNR
  scores, and thumbnails are stored in a local SQLite database, keyed by
  `(path, size, mtime)`. Re-scans of the same folder are dramatically faster.
- **Safe deletion** — Recycle Bin / Quarantine / Permanent. The engine **always
  keeps at least one file per group**; permanent delete requires typed
  confirmation.

## Prerequisites

VidComp needs **Python 3.10+** and three external command-line tools on PATH.

### Required

1. **ffmpeg** and **ffprobe** — install a Windows build, e.g. the
   "release full" zip from https://www.gyan.dev/ffmpeg/builds/ . Extract the
   `bin` folder and add it to your `PATH` (System Properties → Environment
   Variables).
2. After installing, verify in a new PowerShell window:

   ```powershell
   ffmpeg -version
   ffprobe -version
   ```

### Optional but recommended

3. **fpcalc** (Chromaprint) — required for M9 audio fingerprinting. Download
   the Windows binary from https://acoustid.org/chromaprint and add it to
   `PATH`. Verify with `fpcalc -version`.
4. **libvmaf** in your ffmpeg build — required for M8 VMAF. Most "essentials"
   ffmpeg builds **do not** include it; use a "full" build (gyan.dev "full")
   or BtbN's `master-latest-win64-gpl.zip` to get it. VidComp auto-detects this
   and disables the M8 toggle with an explanatory tooltip if libvmaf is missing.

If any required tool is missing on launch, VidComp shows a friendly dialog
with download links and PATH instructions instead of crashing.

## Install

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

Useful flags:

```powershell
python main.py --self-check          # print external-tool status and exit 0/1
python main.py --folder "D:\Videos"  # pre-fill the folder picker
```

## How it works

### Scan modes

| Mode | Methods enabled | Match logic | When to use |
| ---- | --------------- | ----------- | ----------- |
| **Easy** | M1 size, M3 partial hash, M2 SHA-256, M4 ffprobe metadata | ALL must agree | Find exact byte-identical / re-muxed duplicates fast |
| **Medium** | Easy + M5 perceptual hash | ANY agrees | Also catch re-encoded / resized copies |
| **Robust** | Medium + M6 SSIM, M7 PSNR, M8 VMAF, M9 audio | ANY agrees | Slow, thorough; finds visually-similar and same-audio files |

### Comparison methods

| Id | Method | Kind | What it does |
| -- | ------ | ---- | ------------ |
| M1 | File size | signature | Instant pre-filter; groups by exact byte count |
| M2 | SHA-256 (full) | signature | Proves byte-identical files (cached) |
| M3 | Partial hash | signature | SHA-256 of head + tail + size — fast filter |
| M4 | ffprobe metadata | signature | Duration / resolution / codecs / fps / channels |
| M5 | Perceptual hash | signature (approx.) | pHash of N sampled frames; mean Hamming distance |
| M6 | SSIM | pairwise | Structural similarity via ffmpeg `ssim` filter |
| M7 | PSNR | pairwise | Peak signal-to-noise ratio via ffmpeg `psnr` filter |
| M8 | VMAF | pairwise | Netflix VMAF via ffmpeg `libvmaf` (optional) |
| M9 | Audio fingerprint | signature (approx.) | Chromaprint via `fpcalc`, sliding-window cosine |

The engine always runs cheap signature methods first, then narrows the
candidate pair set by bucketing, then runs the expensive pair-wise methods only
on surviving candidates. Pair-wise SSIM/PSNR/VMAF results and per-file
signatures are cached so re-scans are near-instant.

### Combination logic

Two files are considered duplicates when, depending on the **Match logic**
setting in the Advanced panel:

- **ANY** of the enabled methods agrees (more matches), or
- **ALL** of the enabled methods must agree (stricter).

A method that **abstains** (e.g. ffprobe failed, fingerprint could not be
extracted) does not count for or against the verdict — neither blocking an ALL
match nor elevating an ANY match. This makes the engine robust to
unreadable / corrupt files.

### Keep rules

For each duplicate group, VidComp marks one file as the *keeper* — the file
**not** suggested for deletion. The rule is selectable in the bottom bar:

- Highest resolution (default)
- Largest file size
- Longest duration
- Newest (most recent date)
- Oldest (earliest date)
- Manual selection only

You can change the keeper for any individual group via right-click → *Set as
keeper for this group*.

### Deletion modes

| Mode | What happens | Reversible? |
| ---- | ------------ | ----------- |
| **Recycle Bin** (default) | Sent to Windows Recycle Bin via `send2trash` | Yes |
| **Quarantine** | Moved to a folder of your choice, preserving directory structure | Yes (move back manually) |
| **Permanent** | `os.remove()` — file is unrecoverable | **No** (typed `DELETE` confirmation required) |

**Safety invariant**: VidComp will never delete every file in a group. The
keeper for each group is added to a protected set; if any selected file is in
that set, the delete batch is rejected before any file is touched.

## Configuration & caches

All persistent state lives under `%APPDATA%/VidComp/`:

- `config.json` — settings (preset, thresholds, paths, etc.)
- `cache.sqlite` — hashes, perceptual hashes, ffprobe metadata, pair-wise scores
- `thumbnails/` — disk-bounded LRU cache of 320×180 PNG thumbnails
- `quarantine/` — default quarantine target (configurable)
- `vidcomp.log` — rotating log file (also visible in the in-app Log dock)

You can change any of these paths in **Settings → Preferences**.

## Project layout

```
main.py                       # entry point
requirements.txt
pyinstaller.spec
README.md
vidcomp/
  __init__.py
  config.py                   # AppConfig + presets
  workers.py                  # ScanWorker / DeletionWorker (Qt)
  core/
    models.py                 # VideoFile, MediaMetadata, DuplicateGroup, …
    scanner.py                # recursive folder walker
    media.py                  # ffmpeg / ffprobe / fpcalc wrappers
    cache.py                  # SQLite cache
    thumbnails.py             # async thumbnail extraction + LRU
    engine.py                 # scan pipeline
    grouping.py               # union-find
    keep_rules.py             # keeper-selection strategies
    deletion.py               # recycle / quarantine / permanent
    methods/
      base.py                 # ComparisonMethod ABC + MethodContext
      m1_size.py …  m9_audio.py
  gui/
    main_window.py            # main window + menus + worker wiring
    style.py
    widgets/
      top_bar.py, advanced_panel.py, progress_panel.py, result_tree.py,
      summary_bar.py, settings_dialog.py, delete_confirm_dialog.py,
      delete_report_dialog.py, missing_tools_dialog.py, help_dialog.py,
      about_dialog.py, log_panel.py, _helpers.py
tests/
  test_hash.py, test_metadata.py, test_phash.py, test_grouping.py,
  test_keep_rules.py, test_engine_pipeline.py
```

## Tests

```powershell
python -m pip install pytest
python -m pytest -q
```

The test suite uses small synthetic byte fixtures (no real video files) and
covers hashing, ffprobe-JSON parsing, perceptual-hash distance, union-find
grouping, every keep-rule, and the full engine pipeline (with stubbed methods)
including ANY/ALL combination logic and the abstain semantics. Tests do not
require ffmpeg/ffprobe to be installed.

## Packaging a Windows .exe

VidComp ships a PyInstaller spec:

```powershell
.\.venv\Scripts\Activate.ps1
pip install pyinstaller
pyinstaller pyinstaller.spec
```

This produces `dist/VidComp/VidComp.exe`. The bundle is a one-folder build (a
single `.exe` plus its dependencies in the same folder). **ffmpeg / ffprobe /
fpcalc are *not* bundled** — the user still needs them on PATH. If you want a
self-contained distribution, copy `ffmpeg.exe`, `ffprobe.exe` and `fpcalc.exe`
next to `VidComp.exe` (Windows searches the executable's directory first).

## Troubleshooting

- **"ffmpeg / ffprobe missing" dialog on launch** — install the gyan.dev "full"
  build, extract `bin/`, add to PATH, re-launch.
- **M8 VMAF toggle is greyed out** — your ffmpeg build does not include
  `libvmaf`. Use a "full" build to enable it. VidComp will run without it.
- **M9 audio toggle is greyed out** — `fpcalc` is not on PATH. Install
  Chromaprint and add it to PATH.
- **Scan is very slow on first run, fast on re-runs** — that's expected; the
  cache only fills on the first scan. Subsequent scans skip everything that
  hasn't changed on disk.
- **"Refusing to delete N protected files"** — you selected the keeper of a
  group. Change the keep-rule, or use right-click → *Set as keeper* on the file
  you want to preserve, then re-select.
- **Permanent-delete dialog won't enable** — type the word `DELETE` (all caps)
  in the confirmation field.

## Library choices (vs the original prompt)

- The prompt suggested the `videohash` library. **VidComp uses `imagehash`
  on frames we sample ourselves** via OpenCV/ffmpeg — `videohash` is brittle on
  Windows (last release 2021, shells out to its own ImageMagick/ffmpeg
  pipeline). Sampling frames ourselves also gives us frame-timing control we
  reuse for SSIM/PSNR/VMAF, so it's a net architectural win.
- **AcoustID online matching is not used**. The `pyacoustid` library can do
  online lookups, but for duplicate detection we only need fingerprint
  similarity, which `fpcalc` provides locally. No API key required.

## License

Provided as-is, without warranty. Use at your own risk; double-check what's
about to be deleted before clicking *Delete*.
