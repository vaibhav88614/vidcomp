"""Union-find disjoint-set grouping of duplicate pairs."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from .models import DuplicateGroup, PairResult, VideoFile


class _UnionFind:
    """Classical path-compression + union-by-rank union-find."""

    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}
        self._rank: Dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: str) -> str:
        self.add(x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression
        cur = x
        while self._parent[cur] != root:
            self._parent[cur], cur = root, self._parent[cur]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def groups(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = defaultdict(list)
        for node in self._parent:
            out[self.find(node)].append(node)
        return out


def build_groups(
    files: Iterable[VideoFile],
    matched_pairs: Iterable[PairResult],
) -> List[DuplicateGroup]:
    """Cluster files into duplicate groups using union-find over ``matched_pairs``.

    Files not connected to any other file are dropped — a singleton is not a
    duplicate group.
    """
    by_path: Dict[str, VideoFile] = {f.path: f for f in files}
    uf = _UnionFind()
    pair_results_by_root: Dict[str, Dict[Tuple[str, str], PairResult]] = defaultdict(dict)
    for pr in matched_pairs:
        if pr.path_a not in by_path or pr.path_b not in by_path:
            continue
        uf.union(pr.path_a, pr.path_b)
    # After all unions, bucket the pair-results per root for fast lookup.
    for pr in matched_pairs:
        if pr.path_a not in by_path or pr.path_b not in by_path:
            continue
        root = uf.find(pr.path_a)
        key = tuple(sorted((pr.path_a, pr.path_b)))
        pair_results_by_root[root][key] = pr

    groups: List[DuplicateGroup] = []
    next_id = 1
    for root, members in uf.groups().items():
        if len(members) < 2:
            continue
        member_files = [by_path[p] for p in members if p in by_path]
        if len(member_files) < 2:
            continue
        # Stable ordering: by path
        member_files.sort(key=lambda f: f.path.lower())
        groups.append(
            DuplicateGroup(
                group_id=next_id,
                files=member_files,
                pair_scores=dict(pair_results_by_root.get(root, {})),
            )
        )
        next_id += 1

    # Stable ordering of groups: largest first by reclaimable bytes once a
    # keeper is set; for now order by size of group then by total bytes.
    groups.sort(key=lambda g: (-len(g.files), -sum(f.size for f in g.files)))
    # Re-id after sorting so user-visible ids start at 1.
    for i, g in enumerate(groups, 1):
        g.group_id = i
    return groups
