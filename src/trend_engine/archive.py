"""Durable trend history: daily summaries (KST days) + weekly / monthly views.

Hourly snapshots live in the SQLite store (short-term, pruned). Once a KST day is over, it is
summarised into small, source-neutral JSON files under the archive directory, which is committed
to the repo's `data` branch — so history survives cache loss and grows by ~tens of KB per day.

    archive/
      2026-09-19/
        trends-KR.json     # per keyword: label, hours in ranking, best rank, avg score
        trends-US.json ...
        segments.json      # 연령·성별 top keywords that day
        shopping.json      # 연령·성별 shopping keywords that day (7-day window as of that day)

Period views merge archived days with today's live (partial) summary from the store.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .store import Store

KST = ZoneInfo("Asia/Seoul")
KEEP_PER_DAY = 100
PERIODS = {"week": 7, "month": 30}


def kst_today(now: datetime | None = None) -> date:
    return (now or datetime.now(KST)).astimezone(KST).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=KST)
    return start, start + timedelta(days=1)


# --- daily summaries ------------------------------------------------------------------------
def daily_trends(store: Store, region: str, day: date) -> dict[str, Any] | None:
    start, end = day_bounds(day)
    rows = store.cluster_rows(region, start, end)
    if not rows:
        return None
    snapshots = sorted({r["generated_at"] for r in rows})
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        a = agg.setdefault(r["key"], {"key": r["key"], "label": r["label"], "hours": 0, "best_rank": r["rank"],
                                      "score_sum": 0.0, "first": r["generated_at"], "last": r["generated_at"]})
        a["label"] = r["label"]  # latest wording wins
        if r.get("category"):
            a["category"] = r["category"]
        a["hours"] += 1
        a["best_rank"] = min(a["best_rank"], r["rank"])
        a["score_sum"] += r["score"]
        a["last"] = r["generated_at"]
    items = sorted(agg.values(), key=lambda a: (-a["score_sum"], a["best_rank"]))[:KEEP_PER_DAY]
    for a in items:
        a["avg_score"] = round(a.pop("score_sum") / a["hours"], 1)
    return {"date": day.isoformat(), "region": region, "snapshots": len(snapshots), "keywords": items}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def record_daily_extras(store: Store, day: date, segments: dict | None, shopping: dict | None,
                        youth: dict | None = None) -> None:
    """Keep the latest 연령·쇼핑·10·20대 snapshot of each KST day in the store until it is archived."""
    if youth:
        store.cache_set(f"daily:youth:{day.isoformat()}", {"top_by_segment": youth.get("groups", {}), "labels": {}})
    if segments:
        store.cache_set(f"daily:segments:{day.isoformat()}", {
            "top_by_segment": segments.get("top_by_segment", {}), "labels": segments.get("labels", {})})
    if shopping:
        store.cache_set(f"daily:shopping:{day.isoformat()}", {
            "period": shopping.get("period"), "by_segment": shopping.get("by_segment", {})})


def record_daily(store: Store, day: date, kind: str, data: Any) -> None:
    """Generic daily snapshot (e.g. kind="diffusion"), archived by finalize() once the day is over."""
    store.cache_set(f"daily:{kind}:{day.isoformat()}", data)


def finalize(store: Store, root: Path, regions: list[str], today: date | None = None) -> list[str]:
    """Write summaries for every finished KST day that isn't archived yet. Returns files written."""
    today = today or kst_today()
    written: list[str] = []
    for region in regions:
        days = sorted({datetime.fromisoformat(t).astimezone(KST).date() for t in store.snapshot_times(region)})
        for day in days:
            path = root / day.isoformat() / f"trends-{region}.json"
            if day >= today or path.exists():
                continue
            summary = daily_trends(store, region, day)
            if summary:
                _write_json(path, summary)
                written.append(str(path.relative_to(root)))
    for kind in ("segments", "shopping", "youth", "diffusion"):
        for key in store.cache_keys(f"daily:{kind}:"):
            day = date.fromisoformat(key.rsplit(":", 1)[1])
            path = root / day.isoformat() / f"{kind}.json"
            if day >= today or path.exists():
                continue
            data = store.cache_get(key, timedelta(days=3650))
            if data:
                _write_json(path, data | {"date": day.isoformat()})
                written.append(str(path.relative_to(root)))
    return written


def _load(root: Path, day: date, name: str) -> dict[str, Any] | None:
    path = root / day.isoformat() / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def diffusion_sequences(store: Store, root: Path, days: int = 400, today: date | None = None) -> list[list[int]]:
    """Weekly verdict sequences per keyword out of the archived daily 세대 확산 stages — the POMDP's
    accumulating training data (pomdp.weekly_sequences)."""
    from . import pomdp

    today = today or kst_today()
    daily: dict[str, list[tuple[date, str]]] = {}
    for i in range(days, -1, -1):
        day = today - timedelta(days=i)
        d = _load(root, day, "diffusion.json") or store.cache_get(f"daily:diffusion:{day.isoformat()}", timedelta(days=3650))
        for kw, st in (d or {}).get("stages", {}).items():
            stage = st.get("stage") if isinstance(st, dict) else st
            if stage in pomdp.VERDICTS:
                daily.setdefault(kw, []).append((day, stage))
    return pomdp.weekly_sequences(daily)


# --- period views ---------------------------------------------------------------------------
def period_trends(store: Store, root: Path, region: str, days: int, today: date | None = None,
                  limit: int = 40) -> dict[str, Any]:
    """Most persistent/strong interests over the last `days` KST days (today included, partial)."""
    today = today or kst_today()
    daily: list[dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        d = daily_trends(store, region, day) if day == today else _load(root, day, f"trends-{region}.json")
        if d is None and day != today:
            d = daily_trends(store, region, day)  # not archived yet but still in the store
        if d:
            daily.append(d)

    agg: dict[str, dict[str, Any]] = {}
    for d in daily:
        for k in d["keywords"]:
            a = agg.setdefault(k["key"], {"key": k["key"], "label": k["label"], "days": 0, "hours": 0,
                                          "best_rank": k["best_rank"], "exposure": 0.0, "series": {}})
            a["label"] = k["label"]
            if k.get("category"):
                a["category"] = k["category"]
            a["days"] += 1
            a["hours"] += k["hours"]
            a["best_rank"] = min(a["best_rank"], k["best_rank"])
            # exposure = how long × how strong it trended; the ranking metric for a period
            a["exposure"] += k["hours"] * k["avg_score"]
            a["series"][d["date"]] = k["best_rank"]
    items = sorted(agg.values(), key=lambda a: (-a["exposure"], a["best_rank"]))[:limit]
    first_day = daily[0]["date"] if daily else None
    for a in items:
        a["exposure"] = round(a["exposure"])
        a["since"] = min(a["series"])
        a["new_in_period"] = first_day is not None and a["since"] != first_day and len(daily) > 1
    return {"days": days, "days_available": len(daily), "dates": [d["date"] for d in daily], "items": items}


def category_shares(store: Store, root: Path, days: int = 30, today: date | None = None,
                    kind: str = "youth") -> dict[str, Any]:
    """Per group, how the mix of categories moved over the last `days` days: share of that group's
    keywords in each category, per day. Answers "요즘 10대는 게임에서 패션으로 옮겨가나"."""
    today = today or kst_today()
    dates: list[str] = []
    by_group: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        d = _load(root, day, f"{kind}.json") or store.cache_get(f"daily:{kind}:{day.isoformat()}", timedelta(days=3650))
        if not d:
            continue
        dates.append(day.isoformat())
        for group, rows in d.get("top_by_segment", {}).items():
            counts: dict[str, int] = defaultdict(int)
            for r in rows:
                counts[r.get("category") or "기타"] += 1
            total = sum(counts.values()) or 1
            seen = by_group[group]
            for cat, n in counts.items():
                seen[cat] += [0.0] * (len(dates) - 1 - len(seen[cat]))  # backfill days without this category
                seen[cat].append(round(n / total, 3))
    out: dict[str, dict[str, list[float]]] = {}
    for group, cats in by_group.items():
        out[group] = {c: v + [0.0] * (len(dates) - len(v)) for c, v in cats.items()}
    return {"days": days, "days_available": len(dates), "dates": dates, "by_group": out}


def period_segments(store: Store, root: Path, days: int, today: date | None = None, limit: int = 10,
                    kind: str = "segments", top_n: int = 5) -> dict[str, Any]:
    """Per group: keywords that over-indexed on the most days in the period.
    kind="segments" (오늘 이슈 by age) or "youth" (10·20대 discovery)."""
    today = today or kst_today()
    snaps: list[dict[str, Any]] = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        d = _load(root, day, f"{kind}.json") or store.cache_get(f"daily:{kind}:{day.isoformat()}", timedelta(days=3650))
        if d:
            snaps.append(d)
    out: dict[str, list[dict[str, Any]]] = {}
    acc: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for d in snaps:
        labels = d.get("labels", {})
        for seg, rows in d.get("top_by_segment", {}).items():
            for r in rows[:top_n]:
                if (r.get("affinity") or 0) <= 100:
                    continue
                a = acc[seg].setdefault(r["keyword"], {"keyword": labels.get(r["keyword"], r["keyword"]), "days": 0,
                                                       "aff_sum": 0.0, "vs_sum": 0.0, "kind": r.get("kind", ""),
                                                       "category": r.get("category")})
                a["days"] += 1
                a["aff_sum"] += r["affinity"]
                a["vs_sum"] += r.get("vs_older") or 0.0
    for seg, kws in acc.items():
        rows = sorted(kws.values(), key=lambda a: (-a["days"], -a["aff_sum"]))[:limit]
        out[seg] = [{"keyword": a["keyword"], "days": a["days"], "avg_affinity": round(a["aff_sum"] / a["days"], 1),
                     **({"avg_vs_older": round(a["vs_sum"] / a["days"], 1), "kind": a["kind"]} if a["vs_sum"] else {}),
                     **({"category": a["category"]} if a.get("category") else {})}
                    for a in rows]
    return {"days": days, "days_available": len(snaps), "by_segment": out}
