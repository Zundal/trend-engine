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


def analyze(series_by_age: dict[str, list[tuple[str, float]]], bins: int | None = None,
            volume_pct: dict[str, float] | None = None) -> dict[str, Any]:
    stats = {a: age_stats(weekly(series_by_age[a]), bins) for a in AGE_NAMES if series_by_age.get(a)}
    for a, st in stats.items():
        if volume_pct and a in volume_pct:
            st.volume_pct = round(volume_pct[a], 4)
            st.thin = volume_pct[a] < THIN_PCT
    result = classify(stats)
    result["ages"] = {a: {"rise": s.rise.isoformat() if s.rise else None, "peak": s.peak.isoformat() if s.peak else None,
                          "level": s.level, "surge": s.surge, "volume_pct": s.volume_pct, "thin": s.thin,
                          "strip": s.strip} for a, s in stats.items()}
    first = next(iter(series_by_age.values()), [])
    result["weeks"] = len(weekly(first)) if first else 0
    return result


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


async def track(settings, store, keywords: list[str], weeks: int = 17, today: date | None = None) -> dict[str, Any]:
    """Current stage for each tracked keyword over the last `weeks` weeks."""
    end = (today or date.today()) - timedelta(days=1)  # search data lags ~1 day
    start = end - timedelta(weeks=weeks)
    prof = SegmentProfiler(settings, store)
    groups = {k: [k] for k in dict.fromkeys(k for k in keywords if k.strip())}
    series, vol = await _with_client(prof, lambda: fetch_series(prof, groups, start.isoformat(), end.isoformat()))
    items = []
    for name, by_age in series.items():
        if not by_age:
            continue
        a = analyze(by_age, volume_pct=vol.get(name))
        a["keyword"] = name
        items.append(a)
    order = {"확산 중": 0, "윗세대 상승": 1, "확산 대기": 2, "전 연령 동시": 3, "지나감": 4, "상시 관심": 5}
    items.sort(key=lambda x: (order[x["stage"]], x.get("old_lag_weeks") or 99, x["keyword"]))
    return {"period": [start.isoformat(), end.isoformat()], "items": items, "synthetic": prof.synthetic}


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
