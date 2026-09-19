"""세대 확산 감지: does a trend that 10·20대 picked up spread to older ages, and how fast?

For each keyword we pull daily Korean search volume per age group (10대 … 60대+), roll it up to
weeks, and — per age, against that age's own peak in the window — find when interest took off.
Only *timing* is compared across ages (each age is normalised to itself), never absolute size.

Stages (as of the latest week):
  확산 대기   young ages (10·20대) are active, 40대+ not yet            → 윗세대 시장이 아직 열리기 전
  확산 중     young took off first, 40대+ followed ≥ LAG_WEEKS later   → lag in weeks reported
  전 연령 동시 every active age took off within LAG_WEEKS of each other (news/viral shock)
  윗세대 상승 40대+ booming now while 10·20대 are not — if 10·20대 search it far more and steadily
              (young_steady), the young adopted it before the window: that's diffusion in progress
  지나감      there was a boom, but nobody is near their peak any more
  상시 관심   no boom at all (peak < BOOM × typical level) — evergreen interest like games, big brands

Validated on 8 past Korean fads (see CASES): 하이볼 20대→60대+ ~2 years, 두바이쫀득쿠키 +4 weeks,
먹태깡/포켓몬빵 simultaneous. Search ≠ purchase; this measures attention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .segments import SegmentProfiler

AGES: list[tuple[str, tuple[str, ...]]] = [
    ("10대", ("2",)), ("20대", ("3", "4")), ("30대", ("5", "6")),
    ("40대", ("7", "8")), ("50대", ("9", "10")), ("60대+", ("11",)),
]
AGE_NAMES = [a for a, _ in AGES]
YOUNG = ("10대", "20대")
OLD = ("40대", "50대", "60대+")
LAG_WEEKS = 2  # older ages rising ≥ 2 weeks after young = real diffusion, not a shared news shock
ACTIVE = 0.5  # an age is "active" while its recent level is ≥ 50% of its own window peak
BOOM = 1.6  # an age "booms" only if its peak is ≥ 1.6× its baseline (else it's steady interest)
# baseline = min(first 3 weeks, median): catches trends that rose early and stayed up (median would
# already be high) while evergreen interest (flat from the start) stays below BOOM.
BATCH = 4  # + 1 anchor per request (DataLab max 5 groups)
ANCHOR = "날씨"
# An age's data is "thin" below this volume (% of the anchor). Thin ages are shown but excluded from
# the verdict: at tiny volumes a handful of searches looks like a boom (e.g. 60대 × 피규어).
THIN_PCT = 0.005

# Past fads, each with a window around its boom. Recomputed monthly by the same code path.
CASES: dict[str, dict[str, Any]] = {
    "하이볼": {"keywords": ["하이볼"], "window": ("2020-06-01", "2024-06-30")},
    "요아정": {"keywords": ["요아정", "요거트아이스크림의정석"], "window": ("2024-03-01", "2024-12-31")},
    "두바이쫀득쿠키": {"keywords": ["두바이쫀득쿠키", "두바이 쫀득쿠키", "두쫀쿠"], "window": ("2025-09-01", "2026-04-30")},
    "탕후루": {"keywords": ["탕후루"], "window": ("2023-01-01", "2024-03-31")},
    "먹태깡": {"keywords": ["먹태깡"], "window": ("2023-05-01", "2023-10-31")},
    "포켓몬빵": {"keywords": ["포켓몬빵"], "window": ("2022-01-01", "2022-07-31")},
    "러닝크루": {"keywords": ["러닝크루"], "window": ("2024-06-01", "2025-01-31")},
}


# --- pure analysis ------------------------------------------------------------------------
def _d(period: str) -> date:
    return date(int(period[:4]), int(period[4:6]), int(period[6:8])) if len(period) == 8 else date.fromisoformat(period[:10])


def weekly(points: list[tuple[str, float]]) -> list[tuple[date, float]]:
    """Daily (period, ratio) -> Monday-anchored weekly sums over *complete* weeks only (a partial
    first/last week would read as a fake dip), then a 3-week trailing mean to damp noise."""
    acc: dict[date, float] = {}
    days: dict[date, int] = {}
    for p, v in points:
        d = _d(p)
        wk = d - timedelta(days=d.weekday())
        acc[wk] = acc.get(wk, 0.0) + float(v)
        days[wk] = days.get(wk, 0) + 1
    full = {wk: v for wk, v in acc.items() if days[wk] == 7}
    weeks = sorted((full or acc).items())
    out = []
    for i, (wk, _) in enumerate(weeks):
        window = [v for _, v in weeks[max(0, i - 2): i + 1]]
        out.append((wk, sum(window) / len(window)))
    return out


@dataclass
class AgeStats:
    rise: date | None  # first week of the run-up to the peak that reached 50% of peak
    peak: date | None
    level: float  # recent level (last 2 weeks) / own window peak, 0..1
    strip: list[float]  # normalised series for display
    surge: float = 0.0  # peak / baseline
    volume_pct: float | None = None  # window volume as % of the anchor keyword in the same age
    thin: bool = False

    @property
    def boom(self) -> bool:
        return not self.thin and self.surge >= BOOM

    @property
    def active(self) -> bool:
        return self.boom and self.level >= ACTIVE


def age_stats(ws: list[tuple[date, float]], bins: int | None = None) -> AgeStats:
    if not ws or max(v for _, v in ws) <= 0:
        return AgeStats(None, None, 0.0, [0.0] * (bins or len(ws)))
    peak_i = max(range(len(ws)), key=lambda i: ws[i][1])
    peak = ws[peak_i][1]
    i = peak_i
    while i > 0 and ws[i - 1][1] >= 0.5 * peak:
        i -= 1
    recent = [v for _, v in ws[-2:]]
    norm = [v / peak for _, v in ws]
    if bins and len(norm) > bins:  # downsample long windows for display
        step = len(norm) / bins
        norm = [max(norm[int(k * step): max(int((k + 1) * step), int(k * step) + 1)]) for k in range(bins)]
    vals = sorted(v for _, v in ws)
    head = [v for _, v in ws[:3]]
    baseline = min(sum(head) / len(head), vals[len(vals) // 2])
    surge = round(peak / baseline, 2) if baseline > 0 else 99.0
    return AgeStats(ws[i][0], ws[peak_i][0], round(sum(recent) / len(recent) / peak, 3), [round(x, 3) for x in norm], surge)


def classify(stats: dict[str, AgeStats]) -> dict[str, Any]:
    """Stage + per-age lag (weeks) relative to the earliest young take-off."""
    young_rises = [stats[a].rise for a in YOUNG if a in stats and stats[a].rise]
    base = min(young_rises) if young_rises else None
    lags = {a: ((s.rise - base).days // 7 if base and s.rise else None) for a, s in stats.items()}
    young_active = any(stats[a].active for a in YOUNG if a in stats)
    old_active = [a for a in OLD if a in stats and stats[a].active]

    if not young_active and not old_active:
        stage = "지나감" if any(s.boom for s in stats.values()) else "상시 관심"
    elif young_active and not old_active:
        stage = "확산 대기"
    elif not young_active:
        stage = "윗세대 상승"
    else:
        old_lags = [lags[a] for a in old_active if lags.get(a) is not None]
        stage = "확산 중" if old_lags and min(old_lags) >= LAG_WEEKS else "전 연령 동시"
    old_lag = [lags[a] for a in OLD if lags.get(a) is not None]
    vy = [stats[a].volume_pct for a in YOUNG if a in stats and stats[a].volume_pct is not None]
    vo = [stats[a].volume_pct for a in OLD if a in stats and stats[a].volume_pct is not None]
    return {
        "stage": stage,
        "young_steady": stage == "윗세대 상승" and bool(vy and vo) and max(vy) >= 2 * max(vo),
        "young_start": base.isoformat() if base else None,
        "old_lag_weeks": min(old_lag) if old_lag and stage == "확산 중" else None,
        "lags": lags,
    }


def seasonal_adjust(ws: list[tuple[date, float]], clip: tuple[float, float] = (0.5, 2.0)) -> list[tuple[date, float]]:
    """Divide out last year's seasonal shape: factor(w) = last year's week w ÷ last year's ±6-week average
    around it (so long-term growth is kept, only the recurring bump — 방학, 추석 — is removed).
    Weeks without a last-year reference are dropped; keywords that barely existed last year (< 10% of this
    year's level) are left unadjusted (their "season" is noise)."""
    by = dict(ws)
    this_mean = _mean([v for _, v in ws[-52:]]) or 0.0
    out = []
    for d, v in ws:
        ly = d - timedelta(weeks=52)
        if ly not in by:
            continue
        neigh = [by[x] for k in range(-6, 7) if (x := ly + timedelta(weeks=k)) in by]
        local = _mean(neigh)
        if local <= 0 or local < 0.1 * this_mean:
            f = 1.0
        else:
            f = min(max(by[ly] / local, clip[0]), clip[1])
        out.append((d, v / f))
    return out


def analyze(series_by_age: dict[str, list[tuple[str, float]]], bins: int | None = None,
            volume_pct: dict[str, float] | None = None) -> dict[str, Any]:
    return analyze_weekly({a: weekly(series_by_age[a]) for a in AGE_NAMES if series_by_age.get(a)}, bins, volume_pct)


def analyze_weekly(weekly_by_age: dict[str, list[tuple[date, float]]], bins: int | None = None,
                   volume_pct: dict[str, float] | None = None) -> dict[str, Any]:
    stats = {a: age_stats(ws, bins) for a, ws in weekly_by_age.items() if ws}
    for a, st in stats.items():
        if volume_pct and a in volume_pct:
            st.volume_pct = round(volume_pct[a], 4)
            st.thin = volume_pct[a] < THIN_PCT
    result = classify(stats)
    result["ages"] = {a: {"rise": s.rise.isoformat() if s.rise else None, "peak": s.peak.isoformat() if s.peak else None,
                          "level": s.level, "surge": s.surge, "volume_pct": s.volume_pct, "thin": s.thin,
                          "strip": s.strip} for a, s in stats.items()}
    first = next(iter(weekly_by_age.values()), [])
    result["weeks"] = len(first)
    return result


# --- 상승세 vs 반짝 급등 -----------------------------------------------------------------------
# Descriptive labels, NOT validated predictors (docs/ENGINE.md): on 42 weeks "3 weeks of steady growth"
# looked predictive (lift 1.58) but on 96 weeks it reversed (0.89) — the first result was overfit because
# the rule was picked and scored on the same data. Accuracy is re-measured on every run and shown as-is.
SPIKE_Z, SPIKE_RATIO = 3.0, 1.5
STEADY_STEPS = (1.15, 1.15, 1.10)  # this week / last week, last / 2 weeks ago, 2 / 3 weeks ago
FOLLOW_UP, FOLLOW_GAIN = 14, 1.2   # outcome: 7-day average 14 days later ≥ 1.2× today's


def daily(points: list[tuple[str, float]]) -> list[float]:
    return [v for _, v in sorted(((_d(p), float(v)) for p, v in points))]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _ma(vals: list[float], at: int, n: int = 7) -> float:
    return _mean(vals[at - n + 1: at + 1])


def momentum(vals: list[float], at: int | None = None) -> dict[str, Any] | None:
    """상승세/반짝 at day index `at` (default: last), using only days ≤ at."""
    at = len(vals) - 1 if at is None else at
    if at < 34:
        return None
    base = vals[at - 30: at - 2]
    mu = _mean(base)
    sd = max((sum((x - mu) ** 2 for x in base) / len(base)) ** 0.5, 0.1 * mu, 1e-9)
    level = _mean(vals[at - 2: at + 1])
    z = (level - mu) / sd
    ratio = level / mu if mu > 0 else (99.0 if level > 0 else 0.0)
    w0, w1, w2, w3 = (_ma(vals, at - 7 * i) for i in range(4))
    steady = all(b > 0 and a >= k * b for (a, b), k in zip(((w0, w1), (w1, w2), (w2, w3)), STEADY_STEPS))
    spike = z >= SPIKE_Z and ratio >= SPIKE_RATIO and not steady
    growth = round((w0 / w3 - 1) * 100) if w3 > 0 else None
    return {"steady": steady, "spike": spike, "z": round(z, 1), "ratio": round(ratio, 2), "growth_3w_pct": growth}


def momentum_backtest(vals: list[float]) -> list[dict[str, Any]]:
    out = []
    for at in range(34, len(vals) - FOLLOW_UP):
        m = momentum(vals, at)
        now = _ma(vals, at)
        if m is None or now <= 0:
            continue
        out.append({"steady": m["steady"], "spike": m["spike"], "grew": _ma(vals, at + FOLLOW_UP) >= FOLLOW_GAIN * now})
    return out


def momentum_accuracy(records: list[dict[str, Any]]) -> dict[str, Any]:
    base = _mean([1.0 if r["grew"] else 0.0 for r in records]) if records else None
    out: dict[str, Any] = {"days": len(records), "base_rate": round(base, 3) if base is not None else None}
    for kind in ("steady", "spike"):
        flagged = [r for r in records if r[kind]]
        prec = _mean([1.0 if r["grew"] else 0.0 for r in flagged]) if flagged else None
        out[kind] = {"flagged": len(flagged), "precision": round(prec, 3) if prec is not None else None,
                     "lift": round(prec / base, 2) if prec is not None and base else None}
    return out


# --- backtest: would the verdict have predicted what happened next? ------------------------------
HORIZONS = (4, 8)  # weeks


def _spread_after(ws: list[tuple[date, float]], cut: int, horizon: int) -> bool:
    """Did this (older) age take off in the `horizon` weeks after week index `cut`?"""
    before = [v for _, v in ws[max(0, cut - 3): cut + 1]]
    after = [v for _, v in ws[cut + 1: cut + 1 + horizon]]
    if not before or not after:
        return False
    base = sum(before) / len(before)
    return base > 0 and max(after) >= BOOM * base


def backtest(series_by_age: dict[str, list[tuple[str, float]]], volume_pct: dict[str, float] | None = None,
             window: int = 17, horizons: tuple[int, ...] = HORIZONS) -> list[dict[str, Any]]:
    return backtest_weekly({a: weekly(series_by_age[a]) for a in AGE_NAMES if series_by_age.get(a)},
                           volume_pct, window, horizons)


def backtest_weekly(weekly_by_age: dict[str, list[tuple[date, float]]], volume_pct: dict[str, float] | None = None,
                    window: int = 17, horizons: tuple[int, ...] = HORIZONS) -> list[dict[str, Any]]:
    """Walk forward week by week: stage as of week t (using only weeks ≤ t) vs whether any 40대+
    age took off within the next h weeks. Only cut-offs with the full horizon available are scored."""
    if not weekly_by_age:
        return []
    n = min(len(ws) for ws in weekly_by_age.values())
    thin = {a: bool(volume_pct and a in volume_pct and volume_pct[a] < THIN_PCT) for a in weekly_by_age}
    out = []
    for cut in range(window - 1, n - max(horizons)):
        stats = {}
        for a, ws in weekly_by_age.items():
            st = age_stats(ws[cut - window + 1: cut + 1])
            st.thin = thin[a]
            stats[a] = st
        verdict = classify(stats)
        old_ages = [a for a in OLD if a in weekly_by_age and not thin[a]]
        rec = {"week": weekly_by_age[old_ages[0] if old_ages else next(iter(weekly_by_age))][cut][0].isoformat(),
               "stage": verdict["stage"], "old_active": any(stats[a].active for a in old_ages)}
        for h in horizons:
            rec[f"spread_{h}w"] = any(_spread_after(weekly_by_age[a], cut, h) for a in old_ages)
        out.append(rec)
    return out


def accuracy(records: list[dict[str, Any]], horizons: tuple[int, ...] = HORIZONS) -> dict[str, Any]:
    """Precision of '확산 대기' (young active, older quiet) vs the base rate of older take-off among
    all cut-offs where the older ages were still quiet. lift > 1 = the verdict carries signal."""
    quiet = [r for r in records if not r["old_active"]]
    waiting = [r for r in quiet if r["stage"] == "확산 대기"]
    out: dict[str, Any] = {"cutoffs": len(records), "quiet": len(quiet), "waiting": len(waiting)}
    for h in horizons:
        k = f"spread_{h}w"
        hits, base_hits = sum(r[k] for r in waiting), sum(r[k] for r in quiet)
        precision = hits / len(waiting) if waiting else None
        base = base_hits / len(quiet) if quiet else None
        out[f"{h}w"] = {"hits": hits, "precision": round(precision, 3) if precision is not None else None,
                        "base_rate": round(base, 3) if base is not None else None,
                        "lift": round(precision / base, 2) if precision is not None and base else None}
    return out


# --- data -----------------------------------------------------------------------------------
async def fetch_series(profiler: SegmentProfiler, groups: dict[str, list[str]], start: str, end: str
                       ) -> tuple[dict[str, dict[str, list]], dict[str, dict[str, float]]]:
    """-> (name -> age -> [(period, ratio)], name -> age -> volume % of anchor).
    One request per (age, batch of 4 names + anchor)."""
    names = [n for n in groups if n != ANCHOR]
    out: dict[str, dict[str, list]] = {n: {} for n in names}
    vol: dict[str, dict[str, float]] = {n: {} for n in names}
    for age, codes in AGES:
        for i in range(0, len(names), BATCH):
            batch = names[i: i + BATCH]
            body = {"startDate": start, "endDate": end, "timeUnit": "date", "ages": list(codes),
                    "keywordGroups": [{"groupName": ANCHOR, "keywords": [ANCHOR]}]
                    + [{"groupName": n, "keywords": groups[n][:20]} for n in batch]}
            data = await profiler._post(body)
            sums = {r.get("title"): sum(float(d.get("ratio", 0)) for d in r.get("data", [])) for r in data.get("results", [])}
            anchor = sums.get(ANCHOR, 0.0)
            for r in data.get("results", []):
                if r.get("title") in out:
                    out[r["title"]][age] = [(d["period"], float(d.get("ratio", 0))) for d in r.get("data", [])]
                    if anchor > 0:
                        vol[r["title"]][age] = sums[r["title"]] / anchor * 100
    return out, vol


async def _with_client(profiler: SegmentProfiler, coro_fn):
    import httpx

    own = profiler._client is None and not profiler.settings.offline
    if own:
        profiler._client = httpx.AsyncClient(timeout=profiler.settings.timeout)
    try:
        return await coro_fn()
    finally:
        if own and profiler._client:
            await profiler._client.aclose()
            profiler._client = None


def typical_lags(cases_result: dict[str, Any] | None) -> dict[str, float]:
    """Median 20대→age lag (weeks) over past 확산형 cases — fallback forecast for ages not yet moving."""
    out: dict[str, float] = {}
    items = [c for c in (cases_result or {}).get("items", []) if c.get("stage") == "확산형"]
    for age in OLD:
        lags = sorted(c["lags"][age] for c in items if c["lags"].get(age) is not None and c["lags"][age] >= 0)
        if lags:
            out[age] = float(lags[len(lags) // 2])
    return out


async def track(settings, store, keywords: list[str], weeks: int = 17, today: date | None = None,
                history_weeks: int = 42, typical_lag: dict[str, float] | None = None) -> dict[str, Any]:
    """Current stage for each tracked keyword over the last `weeks` weeks, plus a walk-forward
    backtest over `history_weeks` (same number of requests — only the date range is longer)."""
    end = (today or date.today()) - timedelta(days=1)  # search data lags ~1 day
    start = end - timedelta(weeks=weeks)
    hist_start = end - timedelta(weeks=history_weeks + 54)  # +1 year: seasonal reference (same request count)
    prof = SegmentProfiler(settings, store)
    groups = {k: [k] for k in dict.fromkeys(k for k in keywords if k.strip())}
    series, vol = await _with_client(prof, lambda: fetch_series(prof, groups, hist_start.isoformat(), end.isoformat()))
    items, records, raw_records, m_records = [], [], [], []
    for name, by_age in series.items():
        if not by_age:
            continue
        full = {a: weekly(pts) for a, pts in by_age.items() if pts}
        adj = {a: seasonal_adjust(ws) for a, ws in full.items()}
        raw = {a: full[a][-len(adj[a]):] if adj[a] else full[a][-history_weeks:] for a in full}
        adj = {a: adj[a] or raw[a] for a in full}
        records += [r | {"keyword": name} for r in backtest_weekly(adj, vol.get(name), window=weeks)]
        raw_records += backtest_weekly(raw, vol.get(name), window=weeks)
        rising: dict[str, Any] = {}
        for age in YOUNG:
            if by_age.get(age) and not (vol.get(name, {}).get(age, 1) < THIN_PCT):
                vals = daily(by_age[age])
                m_records += momentum_backtest(vals)
                rising[age] = momentum(vals)
        a = analyze_weekly({x: ws[-weeks:] for x, ws in adj.items()}, volume_pct=vol.get(name))
        if a["stage"] in ("확산 대기", "확산 중"):  # young booming now: a forward-looking forecast makes sense
            from . import bass

            v = vol.get(name, {})
            young_age = "20대" if v.get("20대", 1) >= THIN_PCT else "10대"
            recent = {x: ws[-weeks:] for x, ws in full.items()}
            if recent.get(young_age):
                olders = {x: [val for _, val in recent[x]] for x in OLD if recent.get(x) and v.get(x, 1) >= THIN_PCT}
                fc = bass.forecast([w for w, _ in recent[young_age]], [val for _, val in recent[young_age]],
                                   olders, typical_lag)
                fc["ages"] = {x: f for x, f in fc["ages"].items() if f["weeks_from_now"] >= 0}  # only peaks still ahead
                if fc["ages"]:
                    a["forecast"] = fc
        a["momentum"] = {g: m for g, m in rising.items() if m}
        a["rising_now"] = any(m and m["steady"] for m in rising.values())
        a["spiking_now"] = not a["rising_now"] and any(m and m["spike"] for m in rising.values())
        a["keyword"] = name
        items.append(a)
    order = {"확산 중": 0, "윗세대 상승": 1, "확산 대기": 2, "전 연령 동시": 3, "지나감": 4, "상시 관심": 5}
    items.sort(key=lambda x: (order[x["stage"]], x.get("old_lag_weeks") or 99, x["keyword"]))
    return {"period": [start.isoformat(), end.isoformat()], "items": items, "synthetic": prof.synthetic,
            "accuracy": accuracy(records) | {"history": [(end - timedelta(weeks=history_weeks)).isoformat(), end.isoformat()],
                                             "keywords": len(series), "seasonal_adjusted": True},
            "accuracy_unadjusted": accuracy(raw_records),
            "momentum_accuracy": momentum_accuracy(m_records)}


async def cases(settings, store) -> dict[str, Any]:
    """Past fads, same analysis — the evidence behind the stages."""
    prof = SegmentProfiler(settings, store)

    async def run():
        out = []
        for name, c in CASES.items():
            series, vol = await fetch_series(prof, {name: c["keywords"]}, *c["window"])
            if series.get(name):
                a = analyze(series[name], bins=40, volume_pct=vol.get(name))
                # cases are finished booms: describe the diffusion that happened, not today's state
                a["stage"] = "확산형" if any((a["lags"].get(o) or 0) >= LAG_WEEKS for o in OLD) else "동시형"
                a["keyword"], a["window"] = name, list(c["window"])
                out.append(a)
        return out

    items = await _with_client(prof, run)
    items.sort(key=lambda x: -max((v or 0) for v in x["lags"].values()))
    return {"items": items, "synthetic": prof.synthetic}


def tracked_keywords(youth_today: dict[str, Any] | None, youth_month: dict[str, Any] | None, limit: int = 20) -> list[str]:
    """What to watch: keywords 10·20대 over-index on, today first, then the last 30 days."""
    counts: dict[str, int] = {}
    for src, weight in ((youth_today or {}).get("groups", {}), 3), ((youth_month or {}).get("by_segment", {}), 1):
        for rows in src.values():
            for r in rows[:10]:
                k = r["keyword"]
                counts[k] = counts.get(k, 0) + weight
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:limit]
