"""Plain-language Help dialog explaining scan modes and each method."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


_HELP_HTML = """
<h2>VidComp — how it works</h2>
<p><b>VidComp</b> recursively scans a folder for video files and finds duplicates and
near-duplicates by comparing their <i>content</i>, not their filenames.</p>

<h3>Scan modes</h3>
<ul>
  <li><b>Easy</b> — fastest. Catches files that are byte-identical or share the same
    container/stream metadata.<br>
    Methods: M1 file size, M3 partial hash, M2 SHA-256, M4 ffprobe metadata.</li>
  <li><b>Medium</b> — Easy + perceptual hash on sampled frames. Finds re-encoded,
    resized or re-muxed copies that aren't byte-identical.<br>
    Adds: M5 perceptual hash.</li>
  <li><b>Robust</b> — Medium + frame-by-frame SSIM/PSNR and (optionally) VMAF, plus
    audio fingerprinting. Most thorough; slowest.<br>
    Adds: M6 SSIM, M7 PSNR, M8 VMAF, M9 audio fingerprint.</li>
</ul>

<h3>Methods</h3>
<dl>
  <dt><b>M1 — File size</b></dt>
  <dd>Instant pre-filter. Two files that aren't the same size obviously aren't byte-identical.</dd>
  <dt><b>M2 — SHA-256 full hash</b></dt>
  <dd>Proves byte-identical files. Slow on big files, but cached so repeat scans are fast.</dd>
  <dt><b>M3 — Partial hash</b></dt>
  <dd>SHA-256 of the first + last N bytes of the file plus its size. A great cheap filter.</dd>
  <dt><b>M4 — ffprobe metadata</b></dt>
  <dd>Compares duration, resolution, video codec, fps, audio codec, audio channels.</dd>
  <dt><b>M5 — Perceptual hash (pHash)</b></dt>
  <dd>Samples N frames from each video and hashes them with a perceptual hash. Two videos
    match when the mean Hamming distance between their per-frame hashes is small enough.
    Robust to re-encoding and resizing.</dd>
  <dt><b>M6 — SSIM</b></dt>
  <dd>Structural similarity index from ffmpeg's <code>ssim</code> filter (0..1). Same content
    typically scores 0.95+.</dd>
  <dt><b>M7 — PSNR</b></dt>
  <dd>Peak signal-to-noise ratio (dB) via ffmpeg's <code>psnr</code> filter. Same content
    typically scores 30 dB+ (identical = infinity).</dd>
  <dt><b>M8 — VMAF</b></dt>
  <dd>Netflix's perceptual quality score (0..100) via ffmpeg's <code>libvmaf</code>. Requires
    an ffmpeg build with libvmaf. Same content typically scores 90+.</dd>
  <dt><b>M9 — Audio fingerprint</b></dt>
  <dd>Chromaprint audio fingerprint via the <code>fpcalc</code> tool. Catches files with the
    same audio even if their video is encoded differently.</dd>
</dl>

<h3>Combination logic</h3>
<p>Two files are considered duplicates when, depending on the "Match logic" setting:</p>
<ul>
  <li><b>ANY</b> enabled method agrees (default — more matches), or</li>
  <li><b>ALL</b> enabled methods agree (stricter — fewer matches).</li>
</ul>

<h3>Keep rule</h3>
<p>For each duplicate group, VidComp picks one file to <b>keep</b> based on the
selected rule (largest, newest, highest resolution, etc.). You can change the
keeper for any group via right-click → "Set as keeper".</p>

<h3>Deletion</h3>
<p>Three delete modes are available:</p>
<ul>
  <li><b>Recycle Bin</b> — reversible, recommended.</li>
  <li><b>Quarantine</b> — moves files to a folder of your choice for later review.</li>
  <li><b>Permanent</b> — cannot be undone. Requires typed confirmation.</li>
</ul>
<p><b>Safety:</b> VidComp will never let you delete every file in a group; the
keeper for each group is always protected.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VidComp — Help")
        self.resize(640, 580)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(_HELP_HTML)
        layout.addWidget(browser, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(btns)
