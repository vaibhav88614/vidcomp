"""Scan orchestration: prepare signatures, generate candidates, group matches.

The engine follows the performance rule from the spec: run cheap filters first
(size -> hashes -> perceptual hash) and only escalate to expensive pairwise
metrics (SSIM/PSNR/VMAF/audio) on surviving candidate pairs.

It is fully GUI-independent and communicates progress/log/error purely through
callbacks, so it can be driven from a worker thread or a headless script.
"""

from __future__ import annotations

import itertools
import logging
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..config import ScanOptions
from .cache import SignatureCache
from .media import MediaTools
from .methods import build_method
from .methods.base import MethodContext
from .models import (
    DuplicateGroup,
    MatchEvidence,
    MatchLogic,
    MethodId,
    VideoFile,
)

log = logging.getLogger("vidcomp.engine")

# Callback signatures.
ProgressCb = Callable[[int, int, str], None]   # (done, total, message)
LogCb = Callable[[str], None]
ErrorCb = Callable[[str, str], None]            # (path, message)

# Methods that are cheap signature/bucketing comparisons.
_CHEAP = {MethodId.SIZE, MethodId.SHA256, MethodId.PARTIAL_HASH, MethodId.PHASH}
_EXPENSIVE = {MethodId.SSIM, MethodId.PSNR, MethodId.VMAF, MethodId.AUDIO}

# Above this many files we avoid the all-pairs fallback to stay tractable.
_ALL_PAIRS_CAP = 2500


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


@dataclass
class ScanStats:
    files_total: int = 0
    files_prepared: int = 0
    candidate_pairs: int = 0
    pairs_compared: int = 0
    groups_found: int = 0
    errors: int = 0


class DuplicateEngine:
    """Drives a single scan over a list of discovered :class:`VideoFile`."""

    def __init__(
        self,
        tools: MediaTools,
        options: ScanOptions,
        cache: Optional[SignatureCache] = None,
        on_progress: Optional[ProgressCb] = None,
        on_log: Optional[LogCb] = None,
        on_error: Optional[ErrorCb] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        temp_dir: Optional[str] = None,
    ) -> None:
        self.tools = tools
        self.options = options
        self.cache = cache
        self._progress = on_progress or (lambda d, t, m: None)
        self._log = on_log or (lambda m: None)
        self._on_error = on_error or (lambda p, m: None)
        self._cancelled = is_cancelled or (lambda: False)
        self._own_temp = temp_dir is None
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="vidcomp_")
        self.stats = ScanStats()

    # --- public API --------------------------------------------------------
    def run(self, files: list[VideoFile]) -> list[DuplicateGroup]:
        try:
            return self._run(files)
        finally:
            self._cleanup_temp()

    # --- internals ---------------------------------------------------------
    def _run(self, files: list[VideoFile]) -> list[DuplicateGroup]:
        self.stats.files_total = len(files)
        enabled = set(self.options.enabled_methods)
        log.info(
            "Engine starting: %d files, methods=%s, logic=%s, workers=%d, temp=%s",
            len(files),
            sorted(m.value for m in enabled),
            self.options.match_logic.value,
            int(getattr(self.options, "worker_count", 0)),
            self.temp_dir,
        )
        if not enabled:
            self._log("No comparison methods enabled; nothing to do.")
            return []

        methods = {mid: build_method(mid) for mid in enabled}
        ctx = MethodContext(
            tools=self.tools,
            options=self.options,
            temp_dir=self.temp_dir,
            is_cancelled=self._cancelled,
        )
        # Drop methods that cannot run in this environment (missing tools).
        usable: dict[MethodId, object] = {}
        for mid, m in methods.items():
            if m.available(ctx):  # type: ignore[attr-defined]
                usable[mid] = m
                log.debug("method enabled: %s", mid.value)
            else:
                self._log(f"Method {mid.value} unavailable (missing tool); skipped.")
                log.warning("method disabled (env): %s", mid.value)
        if not usable:
            self._log("No usable comparison methods in this environment.")
            return []

        # Apply min-duration filter early if we can probe.
        files = self._apply_duration_filter(files, usable, ctx)
        if self._cancelled():
            return []

        # Phase 1: prepare per-file signatures.
        log.info("Phase 1/3: preparing per-file signatures (%d files)", len(files))
        self._prepare_signatures(files, usable, ctx)
        if self._cancelled():
            return []

        # Phase 2: generate candidate pairs cheaply.
        log.info("Phase 2/3: generating candidate pairs")
        pairs = self._candidate_pairs(files, usable)
        self.stats.candidate_pairs = len(pairs)
        self._log(f"Evaluating {len(pairs)} candidate pair(s).")
        log.info("Phase 3/3: evaluating %d candidate pair(s)", len(pairs))

        # Phase 3: evaluate pairs (escalating to expensive metrics last).
        uf = _UnionFind(len(files))
        evidence_by_path: dict[str, list[MatchEvidence]] = {}
        total = max(1, len(pairs))
        for done, (i, j) in enumerate(pairs, start=1):
            if self._cancelled():
                return []
            self._progress(done, total, f"Comparing {files[i].name} <-> {files[j].name}")
            self.stats.pairs_compared += 1
            ev = self._evaluate_pair(files[i], files[j], usable, ctx)
            if ev:
                log.debug(
                    "MATCH: %s <-> %s via %s",
                    files[i].name, files[j].name,
                    ",".join(e.method.value for e in ev),
                )
                uf.union(i, j)
                evidence_by_path.setdefault(files[i].path, []).extend(ev)
                evidence_by_path.setdefault(files[j].path, []).extend(ev)

        # Phase 4: build groups from the union-find clusters.
        return self._build_groups(files, uf, evidence_by_path)

    def _apply_duration_filter(self, files, usable, ctx) -> list[VideoFile]:
        min_dur = float(getattr(self.options, "min_duration_seconds", 0.0) or 0.0)
        if min_dur <= 0 or not self.tools.has_ffprobe:
            return files
        kept: list[VideoFile] = []
        for vf in files:
            if self.cache:
                self.cache.load_into(vf)
            if vf.info is None:
                vf.info = self.tools.probe(vf.path)
                if self.cache:
                    self.cache.save(vf)
            if vf.info and vf.info.duration is not None and vf.info.duration < min_dur:
                continue
            kept.append(vf)
        if len(kept) != len(files):
            self._log(f"Filtered out {len(files) - len(kept)} clip(s) below min duration.")
        return kept

    def _prepare_signatures(self, files, usable, ctx) -> None:  # noqa: C901
        log.debug(
            "_prepare_signatures: enabled=%s",
            sorted(m.value for m in usable.keys()),
        )
        enabled = set(usable.keys())
        need_info = bool(enabled & {MethodId.PHASH, MethodId.SSIM, MethodId.PSNR, MethodId.VMAF})

        # Size-bucket optimization: only fully hash files that share a size.
        size_groups: dict[int, list[int]] = {}
        for idx, vf in enumerate(files):
            size_groups.setdefault(vf.size, []).append(idx)
        hash_eligible = {idx for ids in size_groups.values() if len(ids) > 1 for idx in ids}

        total = len(files)
        self._progress(0, total, "Preparing signatures...")

        def prepare_one(idx_vf: tuple[int, VideoFile]) -> tuple[int, Optional[str]]:
            idx, vf = idx_vf
            if self._cancelled():
                return idx, None
            try:
                if self.cache:
                    self.cache.load_into(vf)
                # Metadata / info.
                if need_info and vf.info is None:
                    vf.info = self.tools.probe(vf.path)
                # Hash methods only matter when sizes collide.
                if idx in hash_eligible:
                    if MethodId.PARTIAL_HASH in usable:
                        usable[MethodId.PARTIAL_HASH].prepare(vf, ctx)  # type: ignore[attr-defined]
                    if MethodId.SHA256 in usable:
                        usable[MethodId.SHA256].prepare(vf, ctx)  # type: ignore[attr-defined]
                # Perceptual hash + audio fingerprint apply across sizes.
                if MethodId.PHASH in usable:
                    usable[MethodId.PHASH].prepare(vf, ctx)  # type: ignore[attr-defined]
                if MethodId.AUDIO in usable:
                    usable[MethodId.AUDIO].prepare(vf, ctx)  # type: ignore[attr-defined]
                if self.cache:
                    self.cache.save(vf)
                return idx, None
            except Exception as exc:  # never let one bad file kill the scan
                log.exception("prepare failed for %s", vf.path)
                return idx, str(exc)

        workers = max(1, int(getattr(self.options, "worker_count", 4)))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(prepare_one, (i, vf)): i for i, vf in enumerate(files)}
            for fut in as_completed(futures):
                if self._cancelled():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
                idx, err = fut.result()
                done += 1
                self.stats.files_prepared = done
                vf = files[idx]
                if err:
                    self.stats.errors += 1
                    vf.error = err
                    self._on_error(vf.path, err)
                self._progress(done, total, f"Prepared {vf.name}")

    def _candidate_pairs(self, files, usable) -> list[tuple[int, int]]:
        """Cheap candidate generation: equal-size and close-duration pairs."""
        pairs: set[tuple[int, int]] = set()

        # Equal-size buckets (exact duplicates / remuxes).
        size_groups: dict[int, list[int]] = {}
        for idx, vf in enumerate(files):
            size_groups.setdefault(vf.size, []).append(idx)
        size_bucketed = 0
        for ids in size_groups.values():
            if len(ids) > 1:
                for a, b in itertools.combinations(sorted(ids), 2):
                    pairs.add((a, b))
                    size_bucketed += 1
        log.debug("candidates: %d pair(s) from equal-size buckets", size_bucketed)

        # Close-duration pairs (re-encodes / resizes differ in size).
        before = len(pairs)
        has_durations = any(vf.info and vf.info.duration for vf in files)
        if has_durations:
            indexed = [
                (vf.info.duration, idx)
                for idx, vf in enumerate(files)
                if vf.info and vf.info.duration
            ]
            indexed.sort()
            for a_pos in range(len(indexed)):
                da, ia = indexed[a_pos]
                tol = max(1.0, 0.02 * da)
                for b_pos in range(a_pos + 1, len(indexed)):
                    db, ib = indexed[b_pos]
                    if db - da > tol:
                        break
                    pair = (ia, ib) if ia < ib else (ib, ia)
                    pairs.add(pair)
        log.debug("candidates: +%d pair(s) from duration buckets", len(pairs) - before)

        # Fallback: only expensive/perceptual methods enabled and nothing
        # bucketed - compare all pairs if the set is small enough.
        if not pairs and len(files) > 1 and (set(usable) & (_EXPENSIVE | {MethodId.PHASH})):
            if len(files) <= _ALL_PAIRS_CAP:
                for a, b in itertools.combinations(range(len(files)), 2):
                    pairs.add((a, b))
            else:
                self._log(
                    f"Too many files ({len(files)}) for all-pairs fallback; "
                    "enable size/hash methods to narrow candidates."
                )
        return sorted(pairs)

    def _evaluate_pair(self, a: VideoFile, b: VideoFile, usable, ctx) -> list[MatchEvidence]:
        """Apply enabled methods cheap-first; honor ANY/ALL match logic.

        File size (M1) is treated as a pre-filter for candidate bucketing, not
        as a standalone match vote: two unrelated files that merely share a byte
        size must not be flagged as duplicates.  It only casts a vote when it is
        the single enabled method (a deliberate "group by size" request).
        """
        logic = self.options.match_logic
        voting = list(usable.keys())
        if len(voting) > 1 and MethodId.SIZE in voting:
            voting = [m for m in voting if m != MethodId.SIZE]
        voting_set = set(voting)
        cheap_ids = [m for m in usable if m in _CHEAP and m in voting_set]
        expensive_ids = [m for m in usable if m in _EXPENSIVE and m in voting_set]

        evidence: list[MatchEvidence] = []
        cheap_hits = 0
        cheap_total = len(cheap_ids)

        for mid in cheap_ids:
            ev = usable[mid].compare(a, b, ctx)  # type: ignore[attr-defined]
            if ev:
                evidence.append(ev)
                cheap_hits += 1
            elif logic == MatchLogic.ALL:
                # ALL logic: a single cheap miss already disqualifies the pair.
                return []

        if logic == MatchLogic.ANY and cheap_hits > 0:
            # Already a match; skip expensive metrics for performance.
            return evidence

        # Escalate to expensive metrics only for survivors.
        exp_hits = 0
        for mid in expensive_ids:
            if self._cancelled():
                return []
            ev = usable[mid].compare(a, b, ctx)  # type: ignore[attr-defined]
            if ev:
                evidence.append(ev)
                exp_hits += 1
                if logic == MatchLogic.ANY:
                    return evidence
            elif logic == MatchLogic.ALL:
                return []

        if logic == MatchLogic.ALL:
            # Matched only if every enabled method produced evidence.
            return evidence if len(evidence) == (cheap_total + len(expensive_ids)) else []
        # ANY: matched if anything produced evidence.
        return evidence if evidence else []

    def _build_groups(self, files, uf: _UnionFind, evidence_by_path) -> list[DuplicateGroup]:
        clusters: dict[int, list[int]] = {}
        for idx in range(len(files)):
            clusters.setdefault(uf.find(idx), []).append(idx)

        groups: list[DuplicateGroup] = []
        for ids in clusters.values():
            if len(ids) < 2:
                continue
            g = DuplicateGroup(files=[files[i] for i in ids])
            for i in ids:
                p = files[i].path
                if p in evidence_by_path:
                    g.evidence[p] = list(evidence_by_path[p])
            groups.append(g)

        # Largest groups first for a tidy UI.
        groups.sort(key=lambda g: (-len(g.files), -g.total_size))
        self.stats.groups_found = len(groups)
        self._log(f"Found {len(groups)} duplicate group(s).")
        return groups

    def _cleanup_temp(self) -> None:
        if self._own_temp:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        else:
            # Remove only our transient frame scratch space.
            shutil.rmtree(os.path.join(self.temp_dir, "frames"), ignore_errors=True)
