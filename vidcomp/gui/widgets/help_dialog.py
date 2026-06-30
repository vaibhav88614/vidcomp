"""Help / About dialog explaining scan modes and methods in plain language."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import __app_name__, __version__

_HELP_HTML = f"""
<h2>{__app_name__} {__version__}</h2>
<p>VidComp finds duplicate and visually similar videos by their <i>content</i>,
not their filenames, then helps you delete the extras safely.</p>

<h3>Scan modes</h3>
<ul>
  <li><b>Easy</b> - fast. Finds exact / near-exact copies using file size,
      a quick head+tail hash, full SHA-256, and ffprobe metadata.</li>
  <li><b>Medium</b> - balanced. Everything in Easy plus perceptual hashing of
      sampled frames, so it also catches re-encoded or resized copies.</li>
  <li><b>Robust</b> - thorough but slow. Everything in Medium plus frame SSIM
      and PSNR, optional VMAF, and audio fingerprinting. Expensive checks run
      only on candidates that survive the cheaper filters.</li>
</ul>

<h3>Methods (toggle individually in Advanced)</h3>
<ul>
  <li><b>M1 File size</b> - instant pre-filter grouping equal-sized files.</li>
  <li><b>M2 SHA-256</b> - confirms byte-identical duplicates.</li>
  <li><b>M3 Partial hash</b> - hashes the first+last bytes for a fast pre-check.</li>
  <li><b>M4 Metadata</b> - compares duration, resolution, codec, bitrate, fps,
      audio channels via ffprobe. A match now requires duration
      <i>and</i> identical resolution <i>and</i> at least two more attributes
      to agree, so unrelated clips that merely share a duration are no longer
      grouped together.</li>
  <li><b>M5 Perceptual hash</b> - perceptual fingerprint of sampled frames;
      matches within a Hamming-distance threshold. Computed in-process with
      OpenCV + NumPy so no <code>phash</code> / <code>imagehash</code> /
      <code>scipy</code> install is needed (the upstream <code>phash</code>
      package famously fails to build on Windows). Pairs whose aspect ratios
      or durations differ widely are skipped to avoid false positives from
      coincidental dark or low-detail frames.</li>
  <li><b>M6 SSIM</b> - structural similarity of aligned frames (0-1).</li>
  <li><b>M7 PSNR</b> - peak signal-to-noise ratio in dB.</li>
  <li><b>M8 VMAF</b> - Netflix perceptual quality metric (needs libvmaf).</li>
  <li><b>M9 Audio fingerprint</b> - Chromaprint match of the audio track.</li>
</ul>

<h3>Match logic</h3>
<p><b>ANY</b> flags a pair if a single enabled method agrees (more matches).
<b>ALL</b> requires every enabled method to agree (fewer, stricter matches).</p>

<h3>Keep rule &amp; deletion</h3>
<p>The keep rule decides which file is protected in each group (highest
resolution, largest, longest, newest, oldest, or manual). "Select duplicates"
checks everything except the kept file. Deletion can use the Recycle Bin, a
quarantine folder, or permanent removal - VidComp never deletes every file in a
group.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VidComp - Help & About")
        self.setMinimumSize(640, 560)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(_HELP_HTML)
        layout.addWidget(browser, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
