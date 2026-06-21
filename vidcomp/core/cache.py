"""SQLite-backed cache for hashes, perceptual hashes, metadata and pair scores.

Why SQLite (stdlib ``sqlite3``):
    * Single-file, no extra dependency.
    * Concurrent reads + serialised writes work well across our worker threads.
    * Schema migration is trivial — we use ``PRAGMA user_version``.

Two tables:

``artifacts``
    keyed by ``(path, size, mtime, kind)``.  Stores per-file computed values
    (sha256 hex string, partial hash hex, metadata JSON, perceptual-hash bytes,
    audio fingerprint JSON, etc.).

``pair_results``
    keyed by ``(path_a, path_b, kind)`` where ``path_a < path_b`` for
    canonicalisation.  Stores expensive pair-wise scores (SSIM/PSNR/VMAF).
    Invalidated when either file's mtime changes.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple

LOG = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


class Cache:
    """Thread-safe wrapper around an on-disk SQLite cache file."""

    def __init__(self, db_path: str | Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we use explicit transactions
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            version = cur.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                cur.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS artifacts (
                        path TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        kind TEXT NOT NULL,
                        value BLOB,
                        computed_at REAL NOT NULL,
                        PRIMARY KEY (path, size, mtime, kind)
                    );
                    CREATE INDEX IF NOT EXISTS ix_artifacts_path ON artifacts(path);

                    CREATE TABLE IF NOT EXISTS pair_results (
                        path_a TEXT NOT NULL,
                        path_b TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        score REAL,
                        computed_at REAL NOT NULL,
                        a_mtime REAL NOT NULL,
                        b_mtime REAL NOT NULL,
                        PRIMARY KEY (path_a, path_b, kind)
                    );
                    """
                )
                cur.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    # ------------------------------------------------------------------
    # Generic artifact get/set
    # ------------------------------------------------------------------
    def get_artifact(
        self, path: str, size: int, mtime: float, kind: str
    ) -> Optional[bytes]:
        """Return the cached BLOB for ``(path, size, mtime, kind)`` or None.

        If a row exists for the same ``(path, kind)`` but a different ``mtime``,
        it is deleted so stale data can't accumulate.
        """
        with self._lock:
            cur = self._conn.cursor()
            row = cur.execute(
                "SELECT value, mtime, size FROM artifacts WHERE path=? AND kind=?",
                (path, kind),
            ).fetchone()
            if row is None:
                return None
            value, db_mtime, db_size = row
            if abs(db_mtime - mtime) > 1e-3 or db_size != size:
                cur.execute(
                    "DELETE FROM artifacts WHERE path=? AND kind=?", (path, kind)
                )
                return None
            return bytes(value) if value is not None else b""

    def put_artifact(
        self, path: str, size: int, mtime: float, kind: str, value: bytes
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO artifacts "
                "(path, size, mtime, kind, value, computed_at) "
                "VALUES (?,?,?,?,?,?)",
                (path, size, mtime, kind, sqlite3.Binary(value), time.time()),
            )

    # ------------------------------------------------------------------
    # Typed convenience wrappers
    # ------------------------------------------------------------------
    def get_text(self, path: str, size: int, mtime: float, kind: str) -> Optional[str]:
        data = self.get_artifact(path, size, mtime, kind)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def put_text(self, path: str, size: int, mtime: float, kind: str, value: str) -> None:
        self.put_artifact(path, size, mtime, kind, value.encode("utf-8"))

    # ------------------------------------------------------------------
    # Pair results (SSIM/PSNR/VMAF)
    # ------------------------------------------------------------------
    @staticmethod
    def _canon_pair(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def get_pair(
        self, path_a: str, path_b: str, a_mtime: float, b_mtime: float, kind: str
    ) -> Optional[float]:
        pa, pb = self._canon_pair(path_a, path_b)
        # If the caller passed the pair in non-canonical order, swap the mtimes too.
        if (pa, pb) != (path_a, path_b):
            a_mtime, b_mtime = b_mtime, a_mtime
        with self._lock:
            row = self._conn.execute(
                "SELECT score, a_mtime, b_mtime FROM pair_results "
                "WHERE path_a=? AND path_b=? AND kind=?",
                (pa, pb, kind),
            ).fetchone()
            if row is None:
                return None
            score, db_a_mtime, db_b_mtime = row
            if abs(db_a_mtime - a_mtime) > 1e-3 or abs(db_b_mtime - b_mtime) > 1e-3:
                self._conn.execute(
                    "DELETE FROM pair_results WHERE path_a=? AND path_b=? AND kind=?",
                    (pa, pb, kind),
                )
                return None
            return score

    def put_pair(
        self,
        path_a: str,
        path_b: str,
        a_mtime: float,
        b_mtime: float,
        kind: str,
        score: float,
    ) -> None:
        pa, pb = self._canon_pair(path_a, path_b)
        if (pa, pb) != (path_a, path_b):
            a_mtime, b_mtime = b_mtime, a_mtime
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO pair_results "
                "(path_a, path_b, kind, score, computed_at, a_mtime, b_mtime) "
                "VALUES (?,?,?,?,?,?,?)",
                (pa, pb, kind, score, time.time(), a_mtime, b_mtime),
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
