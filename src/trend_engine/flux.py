"""How fast a country's attention turns over, and how hard it clusters on one thing.

Two numbers per country per day, both from the most-read list we already collect:

  교체율 (turnover)  share of today's top-N that was not in yesterday's top-N.
                    Iñiguez, Pineda, Gershenson & Barabási, *Dynamics of ranking*
                    (Nat Commun 13:1646, 2022): the influx of new elements is what decides how
                    stable a ranking is, and under high influx only the very top holds still.
  쏠림 (top-N share) what share of the day's views the top 10 articles took.

Both are descriptive — no prediction, so nothing to overfit. The one real trap is comparison:
a country's raw level depends on how big its wiki is (measured: r = -0.31 between log daily views
and top-10 share across 18 languages, ~-1.7%p per e-fold), so **we never publish a league table of
countries**. Every number is reported against that country's own recent median.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

TOP_N = 10  # the "top of the list", which is the part that stays stable under high influx
BASELINE_DAYS = 90
MIN_GAP = 0.05  # 5 percentage points: below this a day is just noise, whatever the history says


def turnover(today: list[str], yesterday: list[str], n: int = TOP_N) -> float | None:
    """Share of today's top-n that is new since yesterday. None if either day is too short."""
    if len(today) < n or len(yesterday) < n:
        return None
    prev = set(yesterday[:n])
    return sum(1 for a in today[:n] if a not in prev) / n


def concentration(rows: list[tuple[str, int]], n: int = TOP_N) -> float | None:
    """Share of the day's views taken by the top n articles (of the whole list we hold)."""
    if len(rows) < n:
        return None
    total = sum(v for _, v in rows)
    return sum(v for _, v in rows[:n]) / total if total > 0 else None


def daily(by_day: dict[date, list[tuple[str, int]]], n: int = TOP_N) -> list[dict[str, Any]]:
    """-> one row per day (oldest first) with turnover vs the previous day and concentration."""
    days = sorted(by_day)
    out = []
    for i, day in enumerate(days):
        rows = by_day[day]
        prev = by_day[days[i - 1]] if i and (day - days[i - 1]).days == 1 else None
        out.append({
            "day": day.isoformat(),
            "turnover": turnover([a for a, _ in rows], [a for a, _ in prev], n) if prev else None,
            "concentration": concentration(rows, n),
            "top": [a.replace("_", " ") for a, _ in rows[:3]],
        })
    return out


def _level(value: float, baseline: list[float], high: str, low: str, normal: str) -> tuple[str, float]:
    """Label today against this country's own history, plus the gap in percentage points.
    A day counts as unusual once it clears the country's own spread — but never on less than
    MIN_GAP, so a flat history doesn't make every ripple a headline."""
    med = statistics.median(baseline)
    gap = value - med
    spread = statistics.pstdev(baseline) if len(baseline) > 2 else 0.0
    if abs(gap) >= max(spread, MIN_GAP):
        return (high if gap > 0 else low), gap
    return normal, gap


def summary(rows: list[dict[str, Any]], n: int = TOP_N) -> dict[str, Any] | None:
    """Today vs this country's own recent median. Never compare the raw levels between countries."""
    rows = [r for r in rows if r["concentration"] is not None]
    if len(rows) < 14:
        return None
    today = rows[-1]
    hist = rows[-BASELINE_DAYS - 1: -1] or rows[:-1]
    out: dict[str, Any] = {"day": today["day"], "days": len(rows), "top": today["top"]}

    conc = [r["concentration"] for r in hist]
    label, gap = _level(today["concentration"], conc, "한 곳에 쏠림", "여러 곳에 분산", "평소만큼")
    out["concentration"] = {"value": round(today["concentration"], 4),
                            "median": round(statistics.median(conc), 4),
                            "gap_pp": round(gap * 100, 1), "label": label, "n": n}

    turns = [r["turnover"] for r in hist if r["turnover"] is not None]
    if today["turnover"] is not None and len(turns) >= 7:
        label, gap = _level(today["turnover"], turns, "평소보다 빠른 교체", "평소보다 오래 머무름", "평소 속도")
        out["turnover"] = {"value": round(today["turnover"], 4),
                           "median": round(statistics.median(turns), 4),
                           "gap_pp": round(gap * 100, 1), "label": label,
                           "new_of_n": round(today["turnover"] * n), "n": n}
    out["spark"] = [round(r["turnover"], 3) if r["turnover"] is not None else None for r in rows[-42:]]
    return out


def trend(rows: list[dict[str, Any]], window: int = 180) -> dict[str, Any] | None:
    """Is attention turning over faster than it used to? (Lorenz-Spreen et al., Nat Commun 10:1759,
    2019, report that collective-attention cycles have been getting shorter.) Needs ~1 year."""
    turns = [(r["day"], r["turnover"]) for r in rows if r["turnover"] is not None]
    if len(turns) < 2 * window:
        return None
    old = [v for _, v in turns[:window]]
    new = [v for _, v in turns[-window:]]
    return {"then": {"from": turns[0][0], "to": turns[window - 1][0], "median": round(statistics.median(old), 4)},
            "now": {"from": turns[-window][0], "to": turns[-1][0], "median": round(statistics.median(new), 4)},
            "change_pp": round((statistics.median(new) - statistics.median(old)) * 100, 1)}
