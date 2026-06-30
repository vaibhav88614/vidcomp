"""VidComp application entry point.

Run with::

    python main.py            # normal run (console + file logging)
    python main.py --debug    # verbose DEBUG-level logging

You can also force debug logging via the ``VIDCOMP_DEBUG=1`` environment
variable.  In a PyInstaller frozen build the console window is kept open
(see ``build.ps1`` / ``VidComp.spec``) so any startup / runtime errors are
visible immediately and also written to ``%APPDATA%\\VidComp\\logs\\vidcomp.log``.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import traceback
from logging.handlers import RotatingFileHandler


# --- standard-stream safety (frozen --noconsole builds) --------------------
# When PyInstaller is built with --noconsole, sys.stdout/sys.stderr may be
# ``None``.  We default to the console build, but be defensive anyway so a
# stray ``print`` or logging call never crashes the process.
def _ensure_streams() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    # Best-effort: make stdout line-buffered so debug prints show up promptly
    # when running from a console (Windows cmd / PowerShell).
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _debug_enabled(argv: list[str]) -> bool:
    if os.environ.get("VIDCOMP_DEBUG", "").lower() in {"1", "true", "yes", "on"}:
        return True
    return any(a in {"--debug", "-d"} for a in argv)


def _setup_logging(debug: bool) -> logging.Logger:
    """Log to both a rotating file and the console with verbose context."""
    from vidcomp.config import default_config_dir

    log_dir = default_config_dir() / "logs"
    file_handler: logging.Handler
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "vidcomp.log",
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
    except Exception as exc:
        # Logging to a file is best-effort; never let it stop the app.
        sys.stderr.write(f"[VidComp] WARNING: could not open log file: {exc}\n")
        file_handler = logging.NullHandler()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s [%(threadName)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(fmt)

    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    # Wipe any pre-existing handlers (e.g. a previous main() call in tests).
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(file_handler)
    root.addHandler(console)

    # Qt is chatty; keep its warnings but not at DEBUG firehose level.
    logging.getLogger("PySide6").setLevel(logging.INFO)

    return logging.getLogger("vidcomp.main")


def _install_excepthook(log: logging.Logger) -> None:
    """Route all otherwise-unhandled exceptions through the logger."""

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = hook

    # Also catch exceptions raised in background threads (Python 3.8+).
    try:
        import threading

        def thread_hook(args):  # threading.ExceptHookArgs
            if issubclass(args.exc_type, SystemExit):
                return
            log.critical(
                "Unhandled exception in thread %s:\n%s",
                args.thread.name if args.thread else "?",
                "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                ),
            )

        threading.excepthook = thread_hook  # type: ignore[assignment]
    except Exception:  # pragma: no cover - very old runtimes only
        pass


def _log_startup_banner(log: logging.Logger) -> None:
    from vidcomp import __app_name__, __version__

    log.info("=" * 72)
    log.info("%s %s starting", __app_name__, __version__)
    log.info("python      : %s", sys.version.replace("\n", " "))
    log.info("executable  : %s", sys.executable)
    log.info("platform    : %s", platform.platform())
    log.info("frozen      : %s", _is_frozen())
    log.info("cwd         : %s", os.getcwd())
    log.info("argv        : %s", sys.argv)
    try:
        import PySide6  # type: ignore

        log.info("PySide6     : %s", getattr(PySide6, "__version__", "?"))
    except Exception:  # pragma: no cover - PySide6 always installed in practice
        log.warning("PySide6 import failed")
    log.info("=" * 72)


def main() -> int:
    _ensure_streams()
    debug = _debug_enabled(sys.argv)
    log = _setup_logging(debug)
    _install_excepthook(log)
    _log_startup_banner(log)
    if debug:
        log.debug("DEBUG logging enabled (VIDCOMP_DEBUG or --debug)")

    try:
        # Qt imports are kept inside main so that --help style tooling and the
        # unit tests (which only touch the engine) do not require a display.
        log.debug("Importing PySide6 + vidcomp modules...")
        from PySide6.QtWidgets import QApplication

        from vidcomp import __app_name__
        from vidcomp.config import AppConfig
        from vidcomp.core.media import MediaTools
        from vidcomp.gui.main_window import MainWindow
        from vidcomp.gui.style import apply_theme
        from vidcomp.gui.widgets.tool_check_dialog import ToolCheckDialog

        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

        log.debug("Constructing QApplication")
        app = QApplication(sys.argv)
        app.setApplicationName(__app_name__)
        app.setOrganizationName("VidComp")

        log.debug("Loading persistent config")
        config = AppConfig.load()
        log.debug(
            "Config loaded: mode=%s methods=%s keep_rule=%s delete_mode=%s",
            config.scan_options.mode.value,
            sorted(m.value for m in config.scan_options.enabled_methods),
            config.keep_rule.value,
            config.delete_mode.value,
        )

        apply_theme(app, config.dark_mode)

        log.debug("Detecting external media tools")
        tools = MediaTools()
        log.info(
            "Tools - ffmpeg:%s ffprobe:%s fpcalc:%s vmaf:%s",
            tools.has_ffmpeg, tools.has_ffprobe, tools.has_fpcalc, tools.has_vmaf(),
        )
        for st in tools.status():
            log.info(
                "  %-8s available=%s path=%s%s",
                st.name,
                st.available,
                st.path or "-",
                "  libvmaf=yes" if (st.name == "ffmpeg" and st.has_vmaf) else "",
            )

        log.debug("Building MainWindow")
        window = MainWindow(config, tools)
        window.show()

        if not (tools.has_ffmpeg and tools.has_ffprobe):
            log.warning("ffmpeg/ffprobe missing - showing tool-check dialog")
            ToolCheckDialog(tools.status(), window).exec()

        log.info("Entering Qt event loop")
        rc = app.exec()
        log.info("Qt event loop exited with code %s", rc)
        return rc
    except Exception:
        log.exception("Fatal error during startup")
        # In a console build the traceback is also visible; pause so the user
        # can read it before the window closes.
        if _is_frozen() and sys.stdout is not None and sys.stdout.isatty():
            try:
                input("\n[VidComp] Press Enter to close...")
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
