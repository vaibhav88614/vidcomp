"""End-to-end scan engine: discovery → signatures → pair evaluation → grouping.

Stages
------
A. **Discovery** — scan the folder, drop files smaller than ``min_file_size``
   and (later) shorter than ``min_duration_sec``.
B. **Signature computation** — for every enabled signature-style method,
   compute the per-file signature in parallel via a ``ThreadPoolExecutor``.
C. **Candidate pair generation** — bucket files by their cheapest enabled
   signature (file size, then metadata, then "all-pairs" fallback if neither
   is enabled).  Pairs are deduped and capped per bucket via
   ``max_pairs_per_bucket``.
D. **Pair evaluation** — for every candidate pair, call ``evaluate_pair`` on
   every enabled method (exact-signature, approximate-signature, or pairwise).
   Pair-wise expensive methods (SSIM/PSNR/VMAF) short-circuit early when
   ``match_logic="all"`` and a cheaper method has already disagreed.
E. **Combination** — apply ANY / ALL logic to produce final matched pairs.
F. **Grouping** — union-find over matched pairs into :class:`DuplicateGroup`.
G. **Keep-rule** — mark the recommended keeper per group.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from ..config import (
    AppConfig,
    MATCH_ALL,
    MATCH_ANY,
    METHOD_AUDIO,
    METHOD_METADATA,
    METHOD_PARTIAL_HASH,
    METHOD_PHASH,
    METHOD_PSNR,
    METHOD_SHA256,
    METHOD_SIZE,
    METHOD_SSIM,
    METHOD_VMAF,
)
from . import grouping, keep_rules, media, scanner
from .cache import Cache
from .methods import METHOD_REGISTRY, instantiate_methods
from .methods.base import ComparisonMethod, MethodContext
from .models import (
    DuplicateGroup,
    MatchEvidence,
    MediaMetadata,
    PairResult,
    ScanProgress,
    VideoFile,
)

LOG = logging.getLogger(__name__)


# Cheapest → most expensive (defines short-circuit order in ALL mode).
_METHOD_COST_ORDER: Sequence[str] = (
    METHOD_SIZE,
    METHOD_PARTIAL_HASH,
    METHOD_METADATA,
    METHOD_SHA256,
    METHOD_PHASH,
    METHOD_AUDIO,
    METHOD_PSNR,
    METHOD_SSIM,
    METHOD_VMAF,
)


# ---------------------------------------------------------------------------
# Progress callback type alias
# ---------------------------------------------------------------------------
ProgressFn = Callable[[ScanProgress], None]
GroupReadyFn = Callable[[DuplicateGroup], None]


@dataclass
class EngineResult:
    """Final engine output."""

    groups: List[DuplicateGroup] = field(default_factory=list)
    file_count: int = 0
    skipped: int = 0
    elapsed_sec: float = 0.0
    pair_count: int = 0
    metadata: Dict[str, MediaMetadata] = field(default_factory=dict)


# ---------------------------------------------------------------------------
class Engine:
    """Orchestrates the full scan pipeline."""

    def __init__(
        self,
        config: AppConfig,
        cache: Cache,
        cancel_event: Optional[threading.Event] = None,
        progress_cb: Optional[ProgressFn] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config
        self.cache = cache
        self.cancel_event = cancel_event or threading.Event()
        self.progress_cb = progress_cb or (lambda _p: None)
        self.log_cb = log_cb or (lambda _s: None)
        self.ctx = MethodContext(
            cache=cache, cancel_event=self.cancel_event, config=config
        )
        self._skipped = 0
        self._start = 0.0

    # ------------------------------------------------------------------
    def run(self, root: str | Path) -> EngineResult:
        """Execute the full pipeline."""
        self._start = time.time()
        self._skipped = 0

        methods = self._select_methods()
        if not methods:
            self._emit_progress("No comparison methods enabled — nothing to do.")
            return EngineResult(elapsed_sec=time.time() - self._start)

        # ---- A. Discovery
        self._emit_progress("Scanning folder…")
        files = self._discover_files(root)
        if not files or self.cancel_event.is_set():
            return EngineResult(
                file_count=len(files),
                skipped=self._skipped,
                elapsed_sec=time.time() - self._start,
            )

        # ---- (B-pre) Apply min_duration filter (needs metadata, do it lazily)
        if self.config.min_duration_sec > 0:
            files = self._filter_by_duration(files)
            if not files or self.cancel_event.is_set():
                return EngineResult(
                    file_count=len(files),
                    skipped=self._skipped,
                    elapsed_sec=time.time() - self._start,
                )

        # ---- B. Signature computation (parallel)
        signature_methods = [m for m in methods if m.kind == "signature"]
        signatures = self._compute_signatures(files, signature_methods)
        if self.cancel_event.is_set():
            return EngineResult(
                file_count=len(files),
                skipped=self._skipped,
                elapsed_sec=time.time() - self._start,
            )

        # ---- C. Candidate pair generation
        self._emit_progress("Building candidate pairs…")
        pairs = self._generate_candidate_pairs(files, signatures, methods)
        self._emit_progress(f"Evaluating {len(pairs):,} candidate pair(s)…")

        # ---- D. Pair evaluation
        pair_results = self._evaluate_pairs(pairs, files, signatures, methods)
        if self.cancel_event.is_set():
            return EngineResult(
                file_count=len(files),
                skipped=self._skipped,
                elapsed_sec=time.time() - self._start,
                pair_count=len(pairs),
            )

        # ---- E. Combination logic → matched pairs
        matched = [pr for pr in pair_results if pr.matched]

        # ---- F. Grouping
        groups = grouping.build_groups(files, matched)

        # Backfill metadata for files in groups so the UI and keep-rules have
        # resolution / duration / codec available even when M4 wasn't enabled.
        self._backfill_metadata(groups)

        # ---- G. Keep-rule
        keep_rules.apply_to_all(groups, self.config.keep_rule, ctx=self.ctx)

        elapsed = time.time() - self._start
        self._emit_progress(
            f"Done — {len(groups)} duplicate group(s) found in {elapsed:.1f}s."
        )
        return EngineResult(
            groups=groups,
            file_count=len(files),
            skipped=self._skipped,
            elapsed_sec=elapsed,
            pair_count=len(pairs),
            metadata=dict(self.ctx.metadata_cache),
        )

    # ------------------------------------------------------------------
    def _select_methods(self) -> List[ComparisonMethod]:
        ids = sorted(
            (m for m in self.config.enabled_methods if m in METHOD_REGISTRY),
            key=lambda x: _METHOD_COST_ORDER.index(x) if x in _METHOD_COST_ORDER else 99,
        )
        methods = instantiate_methods(ids)

        # Strip methods whose tool is unavailable, log to user.
        kept: List[ComparisonMethod] = []
        for m in methods:
            if m.id == METHOD_VMAF and not media.has_libvmaf():
                self._log(f"Skipping {m.display_name}: libvmaf not available in ffmpeg.")
                continue
            if m.id == METHOD_AUDIO and not media.has_fpcalc():
                self._log(f"Skipping {m.display_name}: fpcalc not found on PATH.")
                continue
            kept.append(m)
        return kept

    # ------------------------------------------------------------------
    def _discover_files(self, root: str | Path) -> List[VideoFile]:
        files: List[VideoFile] = []

        def on_skip(path: str, reason: str) -> None:
            self._skipped += 1
            self._log(f"skip: {path} — {reason}")

        count = 0
        for vf in scanner.walk_directory(
            root,
            self.config.extensions,
            min_file_size_bytes=self.config.min_file_size_bytes,
            cancel_check=self.cancel_event.is_set,
            on_skip=on_skip,
        ):
            files.append(vf)
            count += 1
            if count % 25 == 0:
                self._emit_progress(
                    "Scanning folder…",
                    current=count,
                    total=count,
                    current_file=vf.path,
                )
        self._emit_progress(
            f"Discovered {len(files):,} video file(s).",
            current=len(files),
            total=len(files),
        )
        return files

    # ------------------------------------------------------------------
    def _filter_by_duration(self, files: List[VideoFile]) -> List[VideoFile]:
        """Skip files shorter than ``min_duration_sec`` (requires ffprobe)."""
        kept: List[VideoFile] = []
        min_dur = float(self.config.min_duration_sec)
        for i, f in enumerate(files, 1):
            if self.cancel_event.is_set():
                return kept
            try:
                md = self._fetch_metadata(f)
            except Exception:  # noqa: BLE001
                md = None
            if md is None or md.duration_sec is None:
                # Keep — we can't tell.
                kept.append(f)
                continue
            if md.duration_sec >= min_dur:
                kept.append(f)
            else:
                self._skipped += 1
                self._log(f"skip (too short {md.duration_sec:.1f}s): {f.path}")
        return kept

    # ------------------------------------------------------------------
    def _fetch_metadata(self, file: VideoFile) -> Optional[MediaMetadata]:
        from .methods.m4_metadata import get_or_fetch_metadata  # local: avoid cycle
        return get_or_fetch_metadata(file, self.ctx)

    # ------------------------------------------------------------------
    def _backfill_metadata(self, groups: List[DuplicateGroup]) -> None:
        """Fetch metadata for any in-group file that hasn't been probed yet."""
        for g in groups:
            for f in g.files:
                if self.cancel_event.is_set():
                    return
                if f.path in self.ctx.metadata_cache:
                    continue
                try:
                    self._fetch_metadata(f)
                except Exception:  # noqa: BLE001
                    continue

    # ------------------------------------------------------------------
    def _compute_signatures(
        self,
        files: List[VideoFile],
        methods: List[ComparisonMethod],
    ) -> Dict[str, Dict[str, Any]]:
        """Return ``{method_id: {file_path: signature}}``."""
        out: Dict[str, Dict[str, Any]] = {m.id: {} for m in methods}
        total_units = len(files) * len(methods)
        if total_units == 0:
            return out

        workers = max(1, int(self.config.worker_count))
        done = 0
        last_emit = time.time()

        def task(m: ComparisonMethod, f: VideoFile) -> Tuple[str, str, Any]:
            try:
                sig = m.compute_signature(f, self.ctx)
            except Exception as exc:  # noqa: BLE001
                self._log(f"{m.display_name} failed on {f.path}: {exc}")
                sig = None
            return m.id, f.path, sig

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: List[Future] = []
            for m in methods:
                for f in files:
                    if self.cancel_event.is_set():
                        break
                    futures.append(pool.submit(task, m, f))
                if self.cancel_event.is_set():
                    break

            for fut in _as_completed_cancellable(futures, self.cancel_event):
                try:
                    method_id, path, sig = fut.result()
                except Exception as exc:  # noqa: BLE001
                    self._log(f"signature task failed: {exc}")
                    continue
                if sig is not None:
                    out[method_id][path] = sig
                done += 1
                now = time.time()
                if now - last_emit > 0.15 or done == total_units:
                    self._emit_progress(
                        "Computing signatures…",
                        current=done,
                        total=total_units,
                        current_file=path,
                    )
                    last_emit = now
        return out

    # ------------------------------------------------------------------
    def _generate_candidate_pairs(
        self,
        files: List[VideoFile],
        signatures: Dict[str, Dict[str, Any]],
        methods: List[ComparisonMethod],
    ) -> List[Tuple[VideoFile, VideoFile]]:
        """Bucket files into candidate pairs.

        Strategy: bucket by the cheapest enabled exact-equality signature
        method.  Falls back to all-pairs if no such method is enabled.  Per
        ``match_logic="all"``, we additionally intersect with each enabled
        exact-equality bucket so we don't waste time on pairs that obviously
        can't match.
        """
        cap = max(1, int(self.config.max_pairs_per_bucket))
        bucket_method = self._pick_bucket_method(methods, signatures)
        all_pairs: Set[Tuple[str, str]] = set()
        files_by_path = {f.path: f for f in files}

        if bucket_method is None:
            # No useful bucketing — N choose 2.
            pairs_iter = combinations(files, 2)
            count_for_warning = len(files) * (len(files) - 1) // 2
            if count_for_warning > cap * 10:
                self._log(
                    f"WARNING: no cheap bucketing method enabled; evaluating "
                    f"{count_for_warning:,} pairs may be slow."
                )
            for a, b in pairs_iter:
                if self.cancel_event.is_set():
                    return []
                pair = self._canon_pair(a, b)
                all_pairs.add(pair)
                if len(all_pairs) >= cap * 100:
                    self._log(
                        f"WARNING: pair cap reached ({cap*100:,}); truncating."
                    )
                    break
        else:
            sig_map = signatures.get(bucket_method.id, {})
            buckets: Dict[Any, List[str]] = defaultdict(list)
            for p, sig in sig_map.items():
                buckets[sig].append(p)
            for sig, paths in buckets.items():
                if self.cancel_event.is_set():
                    return []
                if len(paths) < 2:
                    continue
                bucket_pairs = list(combinations(paths, 2))
                if len(bucket_pairs) > cap:
                    self._log(
                        f"WARNING: bucket of size {len(paths)} produced "
                        f"{len(bucket_pairs):,} pairs — capping at {cap:,}."
                    )
                    bucket_pairs = bucket_pairs[:cap]
                for pa, pb in bucket_pairs:
                    all_pairs.add(self._canon_pair_paths(pa, pb))

        # Materialise as VideoFile tuples in canonical order.
        result: List[Tuple[VideoFile, VideoFile]] = []
        for pa, pb in all_pairs:
            fa = files_by_path.get(pa)
            fb = files_by_path.get(pb)
            if fa is not None and fb is not None:
                result.append((fa, fb))
        return result

    @staticmethod
    def _canon_pair(a: VideoFile, b: VideoFile) -> Tuple[str, str]:
        return (a.path, b.path) if a.path < b.path else (b.path, a.path)

    @staticmethod
    def _canon_pair_paths(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def _pick_bucket_method(
        self,
        methods: List[ComparisonMethod],
        signatures: Dict[str, Dict[str, Any]],
    ) -> Optional[ComparisonMethod]:
        """Return the cheapest enabled equality-based method we can bucket by.

        Approximate methods (pHash, audio) are unsuitable bucketers because
        their equality alone doesn't predict matches.
        """
        cheap_order = (
            METHOD_SIZE,
            METHOD_PARTIAL_HASH,
            METHOD_METADATA,
            METHOD_SHA256,
        )
        by_id = {m.id: m for m in methods}
        for mid in cheap_order:
            if mid in by_id and signatures.get(mid):
                return by_id[mid]
        return None

    # ------------------------------------------------------------------
    def _evaluate_pairs(
        self,
        pairs: List[Tuple[VideoFile, VideoFile]],
        files: List[VideoFile],
        signatures: Dict[str, Dict[str, Any]],
        methods: List[ComparisonMethod],
    ) -> List[PairResult]:
        if not pairs or not methods:
            return []

        # Order methods cheapest → most expensive so short-circuit logic works.
        ordered = sorted(
            methods,
            key=lambda m: _METHOD_COST_ORDER.index(m.id)
            if m.id in _METHOD_COST_ORDER else 99,
        )
        match_logic = self.config.match_logic
        cheap_methods = [m for m in ordered if m.kind == "signature"]
        expensive_methods = [m for m in ordered if m.kind == "pairwise"]

        total = len(pairs)
        done = 0
        last_emit = time.time()
        results: List[PairResult] = []
        results_lock = threading.Lock()

        def cheap_phase(pair: Tuple[VideoFile, VideoFile]) -> Optional[PairResult]:
            """Evaluate cheap methods synchronously; decide whether expensive ones are needed."""
            a, b = pair
            pr = PairResult(path_a=a.path, path_b=b.path)
            for m in cheap_methods:
                if self.cancel_event.is_set():
                    return None
                sig_a = signatures.get(m.id, {}).get(a.path)
                sig_b = signatures.get(m.id, {}).get(b.path)
                ev = m.evaluate_pair(a, b, sig_a, sig_b, self.ctx)
                pr.evidences.append(ev)
                # An abstained evidence is neutral — neither short-circuits nor decides.
                if ev.abstain:
                    continue
                if match_logic == MATCH_ALL and not ev.matched:
                    # Short-circuit: in ALL mode, one disagreement kills the pair.
                    pr.matched = False
                    return pr
            # Decide whether to run expensive methods.
            if match_logic == MATCH_ALL:
                # If we still need every method to agree, we *must* run expensive ones.
                pass
            elif match_logic == MATCH_ANY and any(
                e.matched and not e.abstain for e in pr.evidences
            ):
                # ANY: a cheap method already agreed — skip the expensive phase.
                pr.matched = True
                return pr
            return pr  # caller will run expensive phase

        def expensive_phase(pr: PairResult, pair: Tuple[VideoFile, VideoFile]) -> PairResult:
            a, b = pair
            for m in expensive_methods:
                if self.cancel_event.is_set():
                    return pr
                ev = m.evaluate_pair(a, b, None, None, self.ctx)
                pr.evidences.append(ev)
                if ev.abstain:
                    continue
                if match_logic == MATCH_ALL and not ev.matched:
                    pr.matched = False
                    return pr
            return pr

        def finalize(pr: PairResult) -> PairResult:
            # Consider only non-abstained evidences for the verdict.
            voting = [e for e in pr.evidences if not e.abstain]
            if not voting:
                # No method could decide → not a match.
                pr.matched = False
                return pr
            if match_logic == MATCH_ALL:
                pr.matched = all(e.matched for e in voting)
            else:
                pr.matched = any(e.matched for e in voting)
            return pr

        # We run pairs in parallel.  Each pair runs its cheap+expensive phase
        # in one task; the engine's ThreadPoolExecutor caps concurrency.
        def task(pair: Tuple[VideoFile, VideoFile]) -> Optional[PairResult]:
            pr = cheap_phase(pair)
            if pr is None:
                return None
            # If ANY-logic and cheap already matched, skip expensive.
            if not (match_logic == MATCH_ANY and pr.matched):
                pr = expensive_phase(pr, pair)
            return finalize(pr)

        workers = max(1, int(self.config.worker_count))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(task, p) for p in pairs]
            for fut in _as_completed_cancellable(futures, self.cancel_event):
                try:
                    pr = fut.result()
                except Exception as exc:  # noqa: BLE001
                    self._log(f"pair evaluation failed: {exc}")
                    pr = None
                if pr is not None:
                    with results_lock:
                        results.append(pr)
                done += 1
                now = time.time()
                if now - last_emit > 0.15 or done == total:
                    self._emit_progress(
                        "Comparing pairs…",
                        current=done,
                        total=total,
                    )
                    last_emit = now
        return results

    # ------------------------------------------------------------------
    def _emit_progress(
        self,
        stage: str,
        current: int = 0,
        total: int = 0,
        current_file: str = "",
        note: str = "",
    ) -> None:
        elapsed = time.time() - self._start if self._start else 0.0
        eta = 0.0
        if current > 0 and total > 0 and current < total:
            per = elapsed / current
            eta = per * (total - current)
        p = ScanProgress(
            stage=stage,
            current=current,
            total=total,
            current_file=current_file,
            elapsed_sec=elapsed,
            eta_sec=eta,
            skipped=self._skipped,
            note=note,
        )
        try:
            self.progress_cb(p)
        except Exception:  # noqa: BLE001
            pass

    def _log(self, line: str) -> None:
        LOG.info(line)
        try:
            self.log_cb(line)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
def _as_completed_cancellable(
    futures: List[Future],
    cancel_event: threading.Event,
):
    """Like :func:`concurrent.futures.as_completed`, but honours cancel_event.

    When the event is set, in-flight futures are cancelled (best-effort) and
    we stop iterating.
    """
    pending = set(futures)
    while pending:
        if cancel_event.is_set():
            for fut in pending:
                fut.cancel()
            return
        done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
        for fut in done:
            yield fut
