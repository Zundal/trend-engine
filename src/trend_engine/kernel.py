"""세대 전달 함수: the *shape* of a handover between age groups, not a single lag number.

`diffusion.py` answers "how many weeks later did 40대 take off" — one number per keyword, thrown
away as soon as it is read. This module asks the fuller question: treat the older age's weekly
curve as the younger age's curve run through an unknown filter,

    old(t)  ≈  c + Σ_{k=0..K} h(k) · young(t−k),      h(k) ≥ 0, h smooth

and estimate h from many keywords at once. What h gives that a lag cannot:

  · **shape** — mass spread over k=3…6 means a gradual handover, a single spike means an echo
  · **strength** — Σh is how much of the young wave arrives at all
  · **shared shocks** — mass at k=0 is not diffusion, it is both ages reacting to the same news,
    which is the thing the "전 연령 동시" stage currently decides with a threshold
  · **prediction** — convolving today's young curve with h forecasts the older curve

Fitted by projected gradient on the normal equations (K+2 unknowns, so this is small and exact
enough in pure Python — no numpy). Second-difference penalty keeps h smooth; h ≥ 0 because a
handover cannot subtract attention. The intercept c is free.

Nothing here ships unless it beats both baselines in `evaluate`: the single best lag (what the
engine does today) and persistence (old(t) = old(t−1)).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

K_MAX = 12  # weeks of memory: a handover slower than a quarter is two events, not one
SMOOTH = 2.0  # second-difference penalty on h
MIN_ROWS = 60  # below this the fit is fantasy


@dataclass
class Kernel:
    h: list[float]  # h[k] = weight of young(t−k)
    c: float  # intercept
    rows: int
    keywords: int = 0

    @property
    def gain(self) -> float:
        """How much of the young wave reaches the older age, in each side's own-peak units."""
        return sum(self.h)

    @property
    def peak_lag(self) -> int:
        return max(range(len(self.h)), key=lambda k: self.h[k]) if self.gain else 0

    @property
    def mean_lag(self) -> float:
        return sum(k * v for k, v in enumerate(self.h)) / self.gain if self.gain else 0.0

    @property
    def instant_share(self) -> float:
        """Mass at lag 0 — the part that is a shared shock rather than a handover."""
        return self.h[0] / self.gain if self.gain else 0.0

    @property
    def spread(self) -> float:
        """Weighted sd of the lag: small = a sharp echo, large = a gradual spread."""
        if not self.gain:
            return 0.0
        m = self.mean_lag
        return (sum(v * (k - m) ** 2 for k, v in enumerate(self.h)) / self.gain) ** 0.5

    def apply(self, young: list[float], t: int) -> float:
        return self.c + sum(self.h[k] * young[t - k] for k in range(len(self.h)) if 0 <= t - k)

    def to_dict(self) -> dict[str, Any]:
        return {"h": [round(v, 4) for v in self.h], "gain": round(self.gain, 3),
                "peak_lag": self.peak_lag, "mean_lag": round(self.mean_lag, 2),
                "spread": round(self.spread, 2), "instant_share": round(self.instant_share, 3),
                "rows": self.rows, "keywords": self.keywords}


def normalise(ws: list[float]) -> list[float]:
    """Each age against its own peak — only timing and shape are comparable across ages."""
    top = max(ws) if ws else 0
    return [v / top for v in ws] if top > 0 else list(ws)


def rows_for(young: list[float], old: list[float], k_max: int = K_MAX) -> list[tuple[list[float], float]]:
    """One row per week that has k_max weeks of young history behind it."""
    n = min(len(young), len(old))
    return [([young[t - k] for k in range(k_max + 1)], old[t]) for t in range(k_max, n)]


def _normal_equations(rows: list[tuple[list[float], float]], k_max: int, lam: float
                      ) -> tuple[list[list[float]], list[float]]:
    m = k_max + 2  # h(0..k_max) + intercept
    g = [[0.0] * m for _ in range(m)]
    b = [0.0] * m
    for xs, y in rows:
        v = xs + [1.0]
        for i in range(m):
            if v[i]:
                b[i] += v[i] * y
                for j in range(m):
                    g[i][j] += v[i] * v[j]
    for i in range(k_max - 1):  # second differences of h: (h[i] - 2h[i+1] + h[i+2])^2
        d = {i: 1.0, i + 1: -2.0, i + 2: 1.0}
        for a, va in d.items():
            for c, vc in d.items():
                g[a][c] += lam * va * vc
    return g, b


def _solve(g: list[list[float]], b: list[float], k_max: int, iters: int = 4000) -> tuple[list[float], float]:
    """Projected gradient: h stays non-negative, the intercept is free."""
    m = len(b)
    lip = max(sum(abs(v) for v in row) for row in g) or 1.0  # Gershgorin bound on the largest eigenvalue
    step = 1.0 / lip
    x = [0.0] * m
    for _ in range(iters):
        grad = [sum(g[i][j] * x[j] for j in range(m)) - b[i] for i in range(m)]
        moved = 0.0
        for i in range(m):
            new = x[i] - step * grad[i]
            if i <= k_max and new < 0:
                new = 0.0
            moved = max(moved, abs(new - x[i]))
            x[i] = new
        if moved < 1e-10:
            break
    return x[:k_max + 1], x[k_max + 1]


def fit(pairs: list[tuple[list[float], list[float]]], k_max: int = K_MAX, lam: float = SMOOTH) -> Kernel | None:
    """pairs = [(young weekly, old weekly)] for one age pair, already normalised."""
    rows: list[tuple[list[float], float]] = []
    for young, old in pairs:
        rows += rows_for(young, old, k_max)
    if len(rows) < MIN_ROWS:
        return None
    h, c = _solve(*_normal_equations(rows, k_max, lam), k_max)
    return Kernel(h=h, c=c, rows=len(rows), keywords=len(pairs))


# --- does it beat what we already do? ------------------------------------------------------
def _best_lag(pairs: list[tuple[list[float], list[float]]], k_max: int) -> tuple[int, float, float]:
    """The engine's current model: one lag, one gain. Fitted the same way, so the comparison is fair."""
    best = (0, 0.0, 0.0, float("inf"))
    for lag in range(k_max + 1):
        xs, ys = [], []
        for young, old in pairs:
            for t in range(lag, min(len(young), len(old))):
                xs.append(young[t - lag])
                ys.append(old[t])
        if len(xs) < MIN_ROWS:
            continue
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        var = sum((x - mx) ** 2 for x in xs)
        gain = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0
        gain = max(gain, 0.0)
        c = my - gain * mx
        err = statistics.fmean(abs(gain * x + c - y) for x, y in zip(xs, ys))
        if err < best[3]:
            best = (lag, gain, c, err)
    return best[0], best[1], best[2]


def evaluate_forecast(train: list[tuple[list[float], list[float]]], test: list[tuple[list[float], list[float]]],
                      horizon: int = 4, k_max: int = K_MAX, lam: float = SMOOTH) -> dict[str, Any] | None:
    """The task this is actually for: the young curve is in front of us, the older age's next weeks
    are not. Hold out the last `horizon` weeks of each test case's OLD series and predict them.

    Baselines, given the same information: the single-lag rule (what the engine does today) and
    flat — the older age stays where it was last seen. Persistence is *not* a fair comparison at
    one step ahead, because these curves are heavily autocorrelated and that baseline gets to see
    the answer from last week; at a real forecast horizon it cannot.
    """
    k = fit(train, k_max, lam)
    if k is None:
        return None
    lag, gain, c = _best_lag(train, k_max)
    errs: dict[str, list[float]] = {"kernel": [], "lag": [], "flat": []}
    for young, old in test:
        n = min(len(young), len(old))
        if n < k_max + horizon + 2:
            continue
        cut = n - horizon  # old is known up to cut-1, young is known throughout
        last = old[cut - 1]
        for t in range(cut, n):
            errs["kernel"].append(abs(k.apply(young, t) - old[t]))
            errs["lag"].append(abs(gain * young[t - lag] + c - old[t]))
            errs["flat"].append(abs(last - old[t]))
    if len(errs["kernel"]) < 8:
        return None
    mae = {name: statistics.fmean(v) for name, v in errs.items()}
    return {"horizon": horizon, "n": len(errs["kernel"]),
            "mae": {name: round(v, 4) for name, v in mae.items()},
            "beats_lag": round(mae["lag"] / mae["kernel"], 3) if mae["kernel"] else None,
            "beats_flat": round(mae["flat"] / mae["kernel"], 3) if mae["kernel"] else None}


def evaluate(train: list[tuple[list[float], list[float]]], test: list[tuple[list[float], list[float]]],
             k_max: int = K_MAX, lam: float = SMOOTH) -> dict[str, Any] | None:
    """Fit on train, score on test. Kernel must beat BOTH the single-lag rule and persistence."""
    k = fit(train, k_max, lam)
    if k is None:
        return None
    lag, gain, c = _best_lag(train, k_max)
    errs: dict[str, list[float]] = {"kernel": [], "lag": [], "persistence": []}
    for young, old in test:
        n = min(len(young), len(old))
        for t in range(k_max, n):
            errs["kernel"].append(abs(k.apply(young, t) - old[t]))
            errs["lag"].append(abs(gain * young[t - lag] + c - old[t]))
            errs["persistence"].append(abs(old[t - 1] - old[t]))
    if len(errs["kernel"]) < 20:
        return None
    mae = {name: statistics.fmean(v) for name, v in errs.items()}
    return {"kernel": k.to_dict(), "n_test": len(errs["kernel"]),
            "mae": {name: round(v, 4) for name, v in mae.items()},
            "beats_lag": round(mae["lag"] / mae["kernel"], 3) if mae["kernel"] else None,
            "beats_persistence": round(mae["persistence"] / mae["kernel"], 3) if mae["kernel"] else None,
            "lag_baseline": {"lag_weeks": lag, "gain": round(gain, 3)}}


# --- two populations ------------------------------------------------------------------------
YOUNG_AGE = "20대"
OLDER_AGES = ["30대", "40대", "50대", "60대+"]
# Trends that actually handed over vs everything else. Fitting them together would average a real
# handover with a crowd of shared news shocks and show neither.
SPREADING = {"확산형", "확산 중", "윗세대 상승"}
EVERYDAY = {"전 연령 동시", "상시 관심", "동시형", "지나감"}
MIN_WEEKS = 20


def split_populations(data: dict[str, Any]) -> dict[str, dict[str, list]]:
    """-> {"유행": {age: [(young, old)…], "_names": [...]}, "일반": {...}} from cached weekly series."""
    out: dict[str, dict[str, Any]] = {"유행": {a: [] for a in OLDER_AGES}, "일반": {a: [] for a in OLDER_AGES}}
    out["유행"]["_names"], out["일반"]["_names"] = [], []
    sources = [(data.get("tracked") or {}, data.get("stages") or {}),
               (data.get("cases") or {}, data.get("case_stages") or {})]
    for series_by_kw, stages in sources:
        for name, by_age in series_by_kw.items():
            stage = stages.get(name)
            group = "유행" if stage in SPREADING else "일반" if stage in EVERYDAY else None
            young = by_age.get(YOUNG_AGE)
            if not group or not young or len(young) < MIN_WEEKS:
                continue
            used = False
            for age in OLDER_AGES:
                old = by_age.get(age)
                if old and len(old) >= MIN_WEEKS:
                    out[group][age].append((normalise(young), normalise(old)))
                    used = True
            if used:
                out[group]["_names"].append(name)
    return {g: v for g, v in out.items() if any(v[a] for a in OLDER_AGES)}


def contrast(groups: dict[str, Any]) -> dict[str, Any] | None:
    """The finding worth stating: a trend that spreads looks nothing like an everyday issue."""
    fad, plain = groups.get("유행", {}).get("ages"), groups.get("일반", {}).get("ages")
    if not fad or not plain:
        return None
    rows = []
    for age in OLDER_AGES:
        f, p = fad.get(age), plain.get(age)
        if f and p:
            rows.append({"age": age, "fad_lag": f["mean_lag"], "plain_lag": p["mean_lag"],
                         "fad_instant": f["instant_share"], "plain_instant": p["instant_share"],
                         "fad_gain": f["gain"], "plain_gain": p["gain"]})
    if not rows:
        return None
    return {"ages": rows,
            "fad_instant": round(statistics.fmean(r["fad_instant"] for r in rows), 3),
            "plain_instant": round(statistics.fmean(r["plain_instant"] for r in rows), 3)}
