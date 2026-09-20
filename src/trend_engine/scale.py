"""기준어 없이 키워드를 한 자로 재기 — putting every keyword on one scale without an anchor.

DataLab normalises **within a request**: five groups come back as ratios against whichever of them
was biggest. To compare keywords across requests the engine currently spends one of the five slots
on a fixed anchor ("날씨") and divides by it.

That works, and it has a cost nobody sees: 날씨 dwarfs a niche keyword, so the niche one comes back
as a handful of near-zero ratios — which is why `diffusion.THIN_PCT` has to drop thin ages outright.
The fix is not a bigger anchor but no anchor: let the requests *overlap*, and every shared keyword
becomes a constraint,

    log(scale_i) − log(scale_j) ≈ log(observed ratio of i to j in the request they shared)

which is an over-determined linear system on a graph (one node per keyword, one edge per shared
request). Least squares on the graph Laplacian gives every keyword a scale at once, uses every
overlap rather than one privileged keyword, and lets us group keywords of similar size together so
none of them is measured against a giant.

Pure functions: no I/O here. `plan` decides what to ask for, `solve` turns the answers into scales.
"""

from __future__ import annotations

import math
from typing import Any

GAUGE = 0.0  # log-scale of the reference keyword (the solution is only defined up to a constant)
MIN_RATIO = 1e-6  # a group that came back as 0 carries no information


def plan(keywords: list[str], size: int = 5, overlap: int = 2) -> list[list[str]]:
    """Batches of `size`, consecutive batches sharing `overlap` keywords, wrapping at the end so the
    graph is a ring rather than a path (a ring has no dangling end whose scale rests on one edge)."""
    if len(keywords) <= size:
        return [list(keywords)]
    step = max(1, size - overlap)
    batches = [keywords[i: i + size] for i in range(0, len(keywords), step)]
    batches = [b for b in batches if len(b) > overlap]
    last = batches[-1]
    if len(last) < size:  # top the final batch up from the front, closing the ring
        last += [k for k in keywords if k not in last][: size - len(last)]
    return batches


def observations(batches: list[dict[str, float]]) -> list[tuple[str, str, float]]:
    """Each request's per-keyword totals -> log-ratio edges between every pair it measured."""
    edges: list[tuple[str, str, float]] = []
    for totals in batches:
        names = [k for k, v in totals.items() if v and v > MIN_RATIO]
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                edges.append((a, b, math.log(totals[a] / totals[b])))
    return edges


def components(edges: list[tuple[str, str, float]], nodes: list[str]) -> list[list[str]]:
    """Keywords that never shared a request with the rest cannot be placed on the same scale."""
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _ in edges:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
    groups: dict[str, list[str]] = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    return sorted(groups.values(), key=len, reverse=True)


def solve(edges: list[tuple[str, str, float]], nodes: list[str], iters: int = 3000
          ) -> tuple[dict[str, float], float]:
    """Least squares for log-scales, by Gauss–Seidel on the graph Laplacian. Returns (scale, rms).

    Scales are relative: the largest component is pinned so its first keyword sits at GAUGE.
    """
    adj: dict[str, list[tuple[str, float]]] = {n: [] for n in nodes}
    for a, b, r in edges:
        if a in adj and b in adj:
            adj[a].append((b, r))  # x_a - x_b = r
            adj[b].append((a, -r))
    x = {n: 0.0 for n in nodes}
    pinned = components(edges, nodes)[0][0] if nodes else None
    for _ in range(iters):
        moved = 0.0
        for n in nodes:
            if n == pinned or not adj[n]:
                continue
            new = sum(x[m] + r for m, r in adj[n]) / len(adj[n])
            moved = max(moved, abs(new - x[n]))
            x[n] = new
        if moved < 1e-12:
            break
    if pinned:
        x[pinned] = GAUGE
    err = [(x[a] - x[b] - r) ** 2 for a, b, r in edges if a in x and b in x]
    rms = math.sqrt(sum(err) / len(err)) if err else 0.0
    return {n: math.exp(v) for n, v in x.items()}, rms


def report(batches: list[dict[str, float]], keywords: list[str]) -> dict[str, Any]:
    """Scales + the diagnostics that say whether to trust them."""
    edges = observations(batches)
    parts = components(edges, keywords)
    scale, rms = solve(edges, keywords)
    return {"scale": {k: round(v, 6) for k, v in scale.items()},
            "edges": len(edges), "keywords": len(keywords),
            "connected": len(parts) == 1, "components": [len(p) for p in parts],
            "rms_log_error": round(rms, 4),
            "orphans": [p[0] for p in parts[1:] if len(p) == 1][:10]}
