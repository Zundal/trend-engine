"""유행의 모양: what kind of attention peak is this?

Lehmann, Gonçalves, Ramasco & Cattuto, *Dynamical Classes of Collective Attention in Twitter*
(WWW 2012, 251–260) deliberately throw away the detailed curve and keep three numbers per peak —
the share of activity **before**, **on**, and **after** the peak day, inside a two-week window
centred on it. Clustering 402 popular hashtags in that space gave four classes (count chosen by
BIC *and* 10-fold cross-validation), which they tie to anticipated events, sudden shocks, and
socially propagated topics.

Reproduced here on 223 sustained Korean bursts before this module existed: 예고형 18%, 하루형 12%,
대칭형 37%, 여운형 32% — the same four shapes, in the same proportions' ballpark.

What is *not* claimed: that the class predicts how long something lasts. The rise-speed → lifetime
rule from Berger & Le Mens (PNAS 106:8146, 2009) was measured on this data and **failed**
(walk-forward lift 0.90–1.07 vs a flat "typical fad" baseline, and the group-level effect vanished
when the burst definition loosened) — see docs/ENGINE.md. This module only labels the shape.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

ENVELOPE = 2.0  # a burst is "on" while the series holds at 2x its own baseline
SURGE = 6.0  # ... and only counts if it reached 6x at the peak
MIN_SIDE = 5  # days on each side; shorter is a blip, not a shape
MIN_BASE = 5.0
MIN_PEAK = 300  # views: fewer than this and the shares are noise
WINDOW = 7  # days each side of the peak — Lehmann's two-week window
TAIL_MARGIN = 3

CLASSES = {
    "예고형": "정점 전부터 서서히 달아올랐다 — 날짜가 예고된 일",
    "하루형": "정점 당일에 관심이 몰렸다 — 하루짜리 사건",
    "대칭형": "오른 만큼 가라앉았다 — 사람들 사이로 퍼진 모양",
    "여운형": "정점 뒤가 더 길었다 — 예고 없이 터지고 오래 회자",
}


@dataclass
class Burst:
    start: date
    peak: date
    end: date | None
    peak_views: int
    rise_days: int
    fall_days: int | None
    baseline: float
    peak_i: int

    @property
    def done(self) -> bool:
        return self.fall_days is not None


def bursts(series: list[tuple[date, int]], envelope: float = ENVELOPE, surge: float = SURGE,
           min_side: int = MIN_SIDE, min_peak: int = MIN_PEAK) -> list[Burst]:
    """Every burst in one daily series: a contiguous run above `envelope x` the series' own median."""
    if len(series) < 60:
        return []
    days = [d for d, _ in series]
    vals = [v for _, v in series]
    base = max(statistics.median(vals), MIN_BASE)
    thr = envelope * base
    out: list[Burst] = []
    i, n = 0, len(vals)
    while i < n:
        if vals[i] < thr:
            i += 1
            continue
        j = i
        while j + 1 < n and vals[j + 1] >= thr:
            j += 1
        p = max(range(i, j + 1), key=lambda k: vals[k])
        finished = j < n - 1 - TAIL_MARGIN
        if vals[p] >= surge * base and vals[p] >= min_peak and p - i >= min_side and (not finished or j - p >= min_side):
            out.append(Burst(start=days[i], peak=days[p], end=days[j] if finished else None, peak_views=vals[p],
                             rise_days=p - i, fall_days=(j - p) if finished else None, baseline=base, peak_i=p))
        i = j + 1
    return out


def triple(series: list[tuple[date, int]], peak_i: int, window: int = WINDOW) -> tuple[float, float, float] | None:
    """(before, on, after) shares of the views inside ±window days of the peak. Sums to 1."""
    vals = [v for _, v in series]
    lo, hi = max(0, peak_i - window), min(len(vals), peak_i + window + 1)
    if peak_i - lo < window or hi - peak_i <= window:  # need a full window on both sides
        return None
    total = sum(vals[lo:hi])
    if total <= 0:
        return None
    before = sum(vals[lo:peak_i]) / total
    on = vals[peak_i] / total
    return before, on, 1 - before - on


def classify(t: tuple[float, float, float]) -> str:
    """Nearest of the four shapes, in the order that resolves overlaps the way the clusters did:
    a single dominant day wins over anything else, then a heavy side, then symmetry."""
    before, on, after = t
    if on >= 0.35:
        return "하루형"
    if before >= 0.45:
        return "예고형"
    if after >= 0.55:
        return "여운형"
    return "대칭형"


def shape_of(series: list[tuple[date, int]], burst: Burst) -> dict[str, Any] | None:
    t = triple(series, burst.peak_i)
    if t is None:
        return None
    return {"peak": burst.peak.isoformat(), "peak_views": burst.peak_views, "rise_days": burst.rise_days,
            "fall_days": burst.fall_days, "shape": classify(t),
            "before": round(t[0], 3), "on": round(t[1], 3), "after": round(t[2], 3)}


def recurs(series: list[tuple[date, int]], burst: Burst, year: int = 365, slack: int = 21,
           ratio: float = 0.4) -> bool | None:
    """Independent of the shape: did the same thing flare again about a year later (or earlier)?
    Scheduled events (설날, 연기대상) should; one-off news should not. This is the cross-check that
    the labels mean something, in the spirit of Crane & Sornette (PNAS 105:15649, 2008) validating
    classes against a signal the classes were not built from."""
    by_day = dict(series)
    others = []
    for sign in (1, -1):
        centre = burst.peak + timedelta(days=sign * year)
        window = [by_day.get(centre + timedelta(days=k)) for k in range(-slack, slack + 1)]
        window = [v for v in window if v is not None]
        if len(window) > slack:  # enough of that period is covered by the series
            others.append(max(window))
    if not others:
        return None
    return max(others) >= ratio * burst.peak_views
