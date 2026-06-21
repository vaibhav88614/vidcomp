"""VidComp entry point.

Usage::

    python main.py              # launch the GUI
    python main.py --self-check # print external-tool status & exit
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path


def _setup_logging(log_path: Path) -> "QtLogHandler | None":
    """Install logging to a rotating file + the in-app Qt handler.

    The Qt handler is returned so :class:`MainWindow` can wire it to the log dock.
    Returns ``None`` when called from ``--self-check`` mode (no Qt available).
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Remove default handlers attached by libraries.
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
                            datefmt="%H:%M:%S")

    # File handler — rotating, capped at ~2 MB × 3 files.
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_h = logging.handlers.RotatingFileHandler(
            str(log_path), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_h.setFormatter(fmt)
        file_h.setLevel(logging.INFO)
        root.addHandler(file_h)
    except OSError as exc:
        print(f"warning: could not open log file {log_path}: {exc}", file=sys.stderr)

    # Console handler (always).
    con_h = logging.StreamHandler(sys.stderr)
    con_h.setFormatter(fmt)
    con_h.setLevel(logging.WARNING)
    root.addHandler(con_h)

    # Qt handler (only if PySide6 is around — i.e. GUI mode).
    try:
        from vidcomp.gui.widgets.log_panel import QtLogHandler
    except ImportError:
        return None
    qt_h = QtLogHandler()
    qt_h.setFormatter(fmt)
    qt_h.setLevel(logging.INFO)
    root.addHandler(qt_h)
    return qt_h


def _print_tool_status() -> int:
    """``--self-check`` mode — exit code 0 if required tools are present."""
    from vidcomp.core import media

    status = media.detect_tools(force=True)
    print(f"VidComp tool detection report:\n")
    print(f"  ffmpeg:  {'OK ' if status.ffmpeg.available else 'MISSING'}  "
          f"{status.ffmpeg.path or ''}")
    print(f"  ffprobe: {'OK ' if status.ffprobe.available else 'MISSING'}  "
          f"{status.ffprobe.path or ''}")
    print(f"  fpcalc:  {'OK ' if status.fpcalc.available else 'MISSING'}  "
          f"{status.fpcalc.path or ''}")
    print(f"  libvmaf: {'present' if status.libvmaf else 'NOT in ffmpeg build'}")
    if status.required_ok:
        print("\nRequired tools are present — VidComp can run.")
        if status.missing_optional:
            print(f"Optional features disabled: {', '.join(status.missing_optional)}")
        return 0
    print("\nERROR: ffmpeg/ffprobe are required and were not found on PATH.",
          file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vidcomp", description=__doc__)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Check external tools (ffmpeg, ffprobe, fpcalc, libvmaf) and exit.",
    )
    parser.add_argument(
        "--folder",
        metavar="PATH",
        help="Pre-fill the folder picker with this path on launch.",
    )
    args = parser.parse_args(argv)

    # Load config early so we know where to log.
    from vidcomp.config import AppConfig

    config = AppConfig.load()
    log_path = Path(config.log_path)
    qt_handler = _setup_logging(log_path)

    if args.self_check:
        return _print_tool_status()

    # ---- GUI mode
    # Ensure high-DPI behaviour is sane on Windows.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("VidComp")
    app.setOrganizationName("VidComp")
    app.setQuitOnLastWindowClosed(True)

    from vidcomp.gui.main_window import MainWindow

    if args.folder:
        config.last_scan_folder = args.folder
    win = MainWindow(config, qt_handler)  # type: ignore[arg-type]
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
