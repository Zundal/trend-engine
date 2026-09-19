"""Bass diffusion model: forecast *when* older ages will peak for a trend 10·20대 already picked up.

The Bass model (1969) splits adoption into innovators (p) and imitators (q):
    weekly interest  f(t) = m · (p+q)²/p · e^{-(p+q)t} / (1 + (q/p)·e^{-(p+q)t})²,   peak at  t* = ln(q/p)/(p+q)

"Shape transfer": the young age's curve is (mostly) observed, so we fit its shape (p, q) there, assume
older ages diffuse with the same shape, and fit only *when it starts* (t0) and *how big* (m) on the
older age's partial data. Pure Python grid search — tiny inputs, no numpy needed.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

P_GRID = [0.002 * (1.35 ** i) for i in range(16)]   # 0.002 … ~0.18
Q_GRID = [0.05 + 0.07 * i for i in range(20)]       # 0.05 … 1.38


def shape(p: float, q: float, t: float) -> float:
    if t < 0:
        return 0.0
    e = math.exp(-(p + q) * t)
    return (p + q) ** 2 / p * e / (1 + (q / p) * e) ** 2


def peak_time(p: float, q: float) -> float:
    return max(math.log(q / p) / (p + q), 0.0) if q > p else 0.0


def _excess(vals: list[float]) -> list[float]:
    """Interest above the pre-trend level (20th percentile) — Bass models the new adoption only."""
    base = sorted(vals)[max(len(vals) // 5 - 1, 0)]
    return [max(v - base, 0.0) for v in vals]


def _fit_m(y: list[float], g: list[float]) -> tuple[float, float]:
    gg = sum(x * x for x in g)
    if gg <= 0:
        return 0.0, float("inf")
    m = max(sum(a * b for a, b in zip(y, g)) / gg, 0.0)
    return m, sum((a - m * b) ** 2 for a, b in zip(y, g))


def onset(y: list[float]) -> int:
    """First week the excess reaches 10% of its maximum so far."""
    top = max(y)
    return next(i for i, v in enumerate(y) if v >= 0.1 * top)


def fit(vals: list[float]) -> dict[str, float] | None:
    """Full fit (p, q, t0, m) on a weekly series. None if there is no rise to fit.
    t0 is pinned near the observed onset: p and t0 are otherwise confounded (a tiny p with an early
    start draws nearly the same curve), and shape transfer needs t0 to mean "when the rise began"."""
    y = _excess(vals)
    if max(y, default=0) <= 0:
        return None
    first = onset(y)
    best = None
    for t0 in range(first - 2, first + 2):
        for p in P_GRID:
            for q in Q_GRID:
                g = [shape(p, q, i - t0) for i in range(len(y))]
                m, sse = _fit_m(y, g)
                if best is None or sse < best["sse"]:
                    best = {"p": p, "q": q, "t0": t0, "m": m, "sse": sse}
    tot = sum((v - sum(y) / len(y)) ** 2 for v in y) or 1.0
    best["r2"] = round(1 - best["sse"] / tot, 3)
    return best


def fit_timing(vals: list[float], p: float, q: float) -> dict[str, float] | None:
    """Fit only t0 and m with a known shape (p, q). Needs the age to have started rising."""
    y = _excess(vals)
    if max(y, default=0) <= 0:
        return None
    best = None
    first = onset(y)
    for t0 in range(first - 2, first + 2):
        g = [shape(p, q, i - t0) for i in range(len(y))]
        m, sse = _fit_m(y, g)
        if m > 0 and (best is None or sse < best["sse"]):
            best = {"t0": t0, "m": m, "sse": sse}
    return best


def young_peak(vals: list[float]) -> tuple[float, str] | None:
    """Young age's peak week: observed if it is clearly past, else the Bass fit's estimate."""
    if not vals or max(vals) <= 0:
        return None
    top = max(range(len(vals)), key=lambda i: vals[i])
    if top <= len(vals) - 3 and vals[-1] < 0.8 * vals[top]:
        return float(top), "observed"
    f = fit(vals)
    if not f or f["r2"] < 0.3:
        return None
    return f["t0"] + peak_time(f["p"], f["q"]), "bass"


def forecast(weeks: list[date], young: list[float], older: dict[str, list[float]],
             typical_lag: dict[str, float] | None = None) -> dict[str, Any]:
    """Peak-week forecast per older age.

    Validated on past 확산형 fads (docs/ENGINE.md): "the older age peaks as much later as it *started*
    later" (MAE 2.7 weeks) beat Bass shape transfer (3.4), so that is the forecast; Bass only estimates the
    young peak when it hasn't happened yet. Ages that haven't started use the typical lag of past cases."""
    yp = young_peak(young)
    out: dict[str, Any] = {"young_peak": None, "ages": {}}
    if yp is None:
        return out
    ypk, how = yp
    y_on = onset(_excess(young))
    out["young_peak"] = {"week": (weeks[0] + timedelta(weeks=round(ypk))).isoformat(), "method": how}
    last = len(weeks) - 1
    for age, vals in older.items():
        ex = _excess(vals)
        started = max(ex, default=0) > 0 and sum(1 for v in ex[-6:] if v > 0.15 * max(ex)) >= 2
        if started:
            pk, method = ypk + (onset(ex) - y_on), "lag"
        elif typical_lag and age in typical_lag:
            pk, method = ypk + typical_lag[age], "typical"
        else:
            continue
        out["ages"][age] = {"method": method, "peak": (weeks[0] + timedelta(weeks=round(pk))).isoformat(),
                            "weeks_from_now": round(pk - last), "lag_vs_young": round(pk - ypk)}
    return out
