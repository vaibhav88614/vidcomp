"""On-disk SQLite cache for expensive per-file signatures.

Everything is keyed by ``(path, size, mtime)`` so that editing or replacing a
file transparently invalidates its cached values, while a repeat scan of an
unchanged tree is near-instant.

The cache is deliberately tolerant: any failure simply behaves as a cache miss
rather than raising, so a corrupt cache never blocks a scan.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Optional

from .models import MediaInfo, VideoFile

log = logging.getLogger("vidcomp.cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signatures (
    path        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime       INTEGER NOT NULL,
    info_json   TEXT,
    sha256      TEXT,
    partial     TEXT,
    phashes     TEXT,
    audio_fp    TEXT,
    audio_dur   REAL,
    thumbnail   TEXT,
    PRIMARY KEY (path, size, mtime)
);
"""


class SignatureCache:
    """Thread-safe wrapper around a small SQLite database."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._open()

    def _open(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(
                self.db_path, check_same_thread=False, timeout=30.0
            )
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            log.info("Signature cache opened at %s", self.db_path)
        except Exception as exc:
            log.warning("Could not open cache at %s: %s", self.db_path, exc)
            self._conn = None

    # --- read --------------------------------------------------------------
    def load_into(self, vf: VideoFile) -> None:
        """Populate ``vf`` in place with any cached signatures."""
        if self._conn is None:
            return
        path, size, mtime = vf.key
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT info_json, sha256, partial, phashes, audio_fp, "
                    "audio_dur, thumbnail FROM signatures "
                    "WHERE path=? AND size=? AND mtime=?",
                    (path, size, mtime),
                )
                row = cur.fetchone()
        except Exception as exc:
            log.debug("cache read failed: %s", exc)
            return
        if not row:
            return
        info_json, sha256, partial, phashes, audio_fp, audio_dur, thumb = row
        if info_json and vf.info is None:
            try:
                vf.info = MediaInfo(**json.loads(info_json))
            except Exception:
                pass
        vf.sha256 = vf.sha256 or sha256
        vf.partial_hash = vf.partial_hash or partial
        if phashes and vf.phashes is None:
            try:
                vf.phashes = json.loads(phashes)
            except Exception:
                pass
        vf.audio_fingerprint = vf.audio_fingerprint or audio_fp
        vf.audio_fp_duration = vf.audio_fp_duration if vf.audio_fp_duration is not None else audio_dur
        if thumb and os.path.isfile(thumb):
            vf.thumbnail_path = vf.thumbnail_path or thumb

    # --- write -------------------------------------------------------------
    def save(self, vf: VideoFile) -> None:
        """Upsert all currently-known signatures for ``vf``."""
        if self._conn is None:
            return
        path, size, mtime = vf.key
        info_json = None
        if vf.info is not None:
            try:
                info_json = json.dumps(vf.info.__dict__)
            except Exception:
                info_json = None
        phashes = json.dumps(vf.phashes) if vf.phashes is not None else None
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO signatures "
                    "(path, size, mtime, info_json, sha256, partial, phashes, "
                    "audio_fp, audio_dur, thumbnail) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(path, size, mtime) DO UPDATE SET "
                    "info_json=COALESCE(excluded.info_json, info_json), "
                    "sha256=COALESCE(excluded.sha256, sha256), "
                    "partial=COALESCE(excluded.partial, partial), "
                    "phashes=COALESCE(excluded.phashes, phashes), "
                    "audio_fp=COALESCE(excluded.audio_fp, audio_fp), "
                    "audio_dur=COALESCE(excluded.audio_dur, audio_dur), "
                    "thumbnail=COALESCE(excluded.thumbnail, thumbnail)",
                    (
                        path, size, mtime, info_json, vf.sha256, vf.partial_hash,
                        phashes, vf.audio_fingerprint, vf.audio_fp_duration,
                        vf.thumbnail_path,
                    ),
                )
                self._conn.commit()
        except Exception as exc:
            log.debug("cache write failed: %s", exc)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
