"""이슈 깊이 읽기 — 지금 뜨는 이슈 하나하나에 다섯 가지 질문을 붙인다. 모두 순수 함수.

  why     왜 뜨나: 붙은 헤드라인 중 다른 제목들과 가장 많이 겹치는 한 줄 (요약 생성 없음, 고르기만)
  origin  누가 먼저: 신호 종류(SNS·포털·검색 급상승·백과 조회·뉴스)별 첫 등장 시각, 최근 3일 기록 기준
  life    일생: 처음 뜬 때·정점·순위권 시간·재등장·지금 국면, 최근 30일 순위 기록 기준
  links   연결: 같은 기사에 함께 나온 다른 이슈 (같은 제목을 공유하거나, 한쪽 제목이 다른 쪽을 언급)
  season  작년 이맘때: 백과 문서 조회수로 본 1년 전 같은 시기 관심 대비

공개 뷰에는 소스 이름 대신 신호 종류만 나간다 (AGENTS.md 불변식 5a).
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Any

from .normalize import mentions, norm_key, tokens

SNS, PORTAL, SURGE, WIKI, NEWS = "SNS", "포털", "검색 급상승", "백과 조회", "뉴스·콘텐츠"
SIGNAL = {
    "google_trends": SURGE,
    "signal_bz": PORTAL, "nate": PORTAL, "zum_issue": PORTAL, "yahoo_topics": PORTAL,
    "yahoo_tw_search": PORTAL, "yahoo_trending": PORTAL,
    "trends24": SNS, "getdaytrends": SNS, "yahoo_realtime": SNS,
    "wikipedia": WIKI,
}
OTHER = "기타 신호"

ORIGIN_WINDOW = timedelta(hours=72)  # report payloads are kept 3 days (Store.prune)
LIFE_WINDOW = timedelta(days=30)
RETURN_GAP = timedelta(hours=48)  # out of the ranking this long, then back = 재등장
PHASE_LOOKBACK = timedelta(hours=6)
FRESH = timedelta(hours=6)
MOVE = 3  # ranks
LINK_TOP = 30
LINKS_PER_ITEM = 4
HUB_SHARE, HUB_MIN = 0.15, 8
LEAD_SHARE = 0.6
USUAL_LIFT = 1.5  # below this the article is at its everyday level: not a seasonal event
SEASON_SLACK = 21  # days either side of "a year ago"
SEASON_RECENT = 14
SEASON_RECUR = 0.4  # same ratio as shapes.recurs
SEASON_NEW = 0.1


def signal_of(source: str) -> str:
    return SIGNAL.get(source, OTHER)


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _titles(c: dict[str, Any]) -> list[str]:
    seen, out = set(), []
    for t in [*c.get("related", []), *(t for ts in (c.get("mentions") or {}).values() for t in ts)]:
        k = norm_key(t)
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out


# --- 왜 뜨나 -----------------------------------------------------------------------------
def why(c: dict[str, Any]) -> dict[str, Any] | None:
    """The headline most other headlines agree with. support = titles telling the same story
    (sharing 2+ words), outlets = distinct kinds of coverage it came from."""
    titles = _titles(c)
    if not titles:
        return None
    own = tokens(c.get("label", "")) | {norm_key(c.get("label", ""))}
    toks = [tokens(t) - own for t in titles]  # sharing only the issue's own name is not agreement
    label = norm_key(c.get("label", ""))

    def score(i: int) -> tuple[int, int, int]:
        support = sum(1 for j, o in enumerate(toks) if j != i and len(toks[i] & o) >= 2)
        return support, int(mentions(label, titles[i])), -len(titles[i])

    best = max(range(len(titles)), key=score)
    support = score(best)[0] + 1
    if support < 2:
        return None  # no second headline tells the same story: nothing agreed on to show
    outlets = len(c.get("mentions") or {}) + (1 if c.get("related") else 0)
    return {"line": titles[best], "support": support, "titles": len(titles), "outlets": outlets}


# --- 누가 먼저 -----------------------------------------------------------------------------
def _match(target: dict[str, Any], clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = {target["key"], *(norm_key(v) for v in target.get("variants", []))} - {""}
    return [c for c in clusters if c["key"] in keys or keys & {norm_key(v) for v in c.get("variants", [])}]


def _signals(c: dict[str, Any]) -> set[str]:
    out = {signal_of(s) for s in c.get("sources", {})}
    if c.get("mentions"):
        out.add(NEWS)
    return out


def origin(target: dict[str, Any], snapshots: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First time each kind of signal carried this issue. `snapshots` = past reports, oldest first.
    If the issue was already there in the oldest snapshot, who was first is unknown — say so."""
    if not snapshots:
        return None
    first: dict[str, str] = {}
    for snap in snapshots:
        for c in _match(target, snap.get("clusters", [])):
            for s in _signals(c):
                first.setdefault(s, snap["generated_at"])
    if not first:
        return None
    start = snapshots[0]["generated_at"]
    path = sorted(({"signal": s, "at": at} for s, at in first.items()), key=lambda p: (p["at"], p["signal"]))
    known = path[0]["at"] > start and (len(path) == 1 or path[0]["at"] < path[1]["at"])
    lead = (_ts(path[1]["at"]) - _ts(path[0]["at"])).total_seconds() / 3600 if known and len(path) > 1 else None
    return {"path": path, "first": path[0]["signal"] if known else None,
            "lead_hours": round(lead, 1) if lead is not None else None, "window_start": start}


def leads(origins: list[dict[str, Any]], min_n: int = 3) -> list[dict[str, Any]]:
    """Across today's issues: how often signal A showed up before signal B, and by how long.
    Caught in the same collection = a tie: counted apart, never as A losing. Only pairs where
    one side leads most of the decided issues are kept (a coin flip says nothing)."""
    pairs: dict[tuple[str, str], list[float]] = {}
    for o in origins:
        if not o:
            continue
        at = {p["signal"]: _ts(p["at"]) for p in o["path"] if p["at"] > o["window_start"]}
        for a, ta in at.items():
            for b, tb in at.items():
                if a < b:
                    pairs.setdefault((a, b), []).append((tb - ta).total_seconds() / 3600)
    out = []
    for (a, b), gaps in pairs.items():
        decided = [g for g in gaps if g != 0]
        if len(decided) < min_n:
            continue
        ahead = sum(1 for g in decided if g > 0)
        lead, lag = (a, b) if 2 * ahead >= len(decided) else (b, a)
        wins = [abs(g) for g in decided if (g > 0) == (lead == a)]
        share = len(wins) / len(decided)
        if share < LEAD_SHARE:
            continue
        out.append({"signal": lead, "before": lag, "n": len(decided), "wins": len(wins),
                    "ties": len(gaps) - len(decided), "share": round(share, 2),
                    "median_hours": round(statistics.median(wins), 1)})
    return sorted(out, key=lambda r: (-r["wins"], -r["share"]))


# --- 일생 ----------------------------------------------------------------------------------
def life(rows: list[dict[str, Any]], latest: str) -> dict[str, Any] | None:
    """rows = [{generated_at, rank}] for one issue, oldest first; latest = newest snapshot time."""
    if not rows:
        return None
    times = [_ts(r["generated_at"]) for r in rows]
    peak = min(rows, key=lambda r: (r["rank"], r["generated_at"]))
    returns = sum(1 for a, b in zip(times, times[1:]) if b - a >= RETURN_GAP)
    stretch = times[0]
    for a, b in zip(times, times[1:]):
        if b - a >= RETURN_GAP:
            stretch = b
    now = _ts(latest)
    current = rows[-1]["rank"] if rows[-1]["generated_at"] == latest else None
    before = [r["rank"] for r, t in zip(rows, times) if t <= now - PHASE_LOOKBACK]
    if current is None:
        phase = "순위 밖"
    elif returns and now - stretch <= RETURN_GAP:
        phase = "재등장"
    elif now - times[0] <= FRESH:
        phase = "막 등장"
    elif current <= peak["rank"] and _ts(peak["generated_at"]) >= now - PHASE_LOOKBACK:
        phase = "정점"
    elif before and before[-1] - current >= MOVE:
        phase = "상승 중"
    elif before and current - before[-1] >= MOVE:
        phase = "내려가는 중"
    else:
        phase = "유지"
    return {"first_seen": rows[0]["generated_at"], "peak_rank": peak["rank"], "peak_at": peak["generated_at"],
            "snapshots": len(rows), "days": len({t.date() for t in times}), "returns": returns,
            "current": current, "phase": phase}


# --- 연결 ----------------------------------------------------------------------------------
def links(clusters: list[dict[str, Any]], top: int = LINK_TOP) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Issues reported together. Edge = headlines both carry, or one's headline naming the other.
    -> ({key: [{key, label, shared, title}]}, groups of 3+ connected issues)."""
    head = clusters[:top]
    titles = {c["key"]: _titles(c) for c in head}
    pool = {norm_key(t): t for ts in titles.values() for t in ts}
    # a name inside a big share of all headlines ('Việt Nam', 'Trump') connects everything = nothing
    hubs = {c["key"] for c in head
            if sum(1 for t in pool.values() if mentions(norm_key(c["label"]), t)) > max(HUB_MIN, HUB_SHARE * len(pool))}
    edges: dict[tuple[str, str], list[str]] = {}
    for i, a in enumerate(head):
        for b in head[i + 1:]:
            ka, kb = norm_key(a["label"]), norm_key(b["label"])
            if a["key"] in hubs or b["key"] in hubs or not ka or not kb or ka in kb or kb in ka:
                continue  # one label inside the other = the same story, already merged as a theme
            shared = {t for t in titles[a["key"]] if mentions(kb, t)} | {t for t in titles[b["key"]] if mentions(ka, t)}
            shared |= {t for t in titles[a["key"]] if norm_key(t) in {norm_key(x) for x in titles[b["key"]]}}
            if shared:
                edges[(a["key"], b["key"])] = sorted(shared, key=len)
    label = {c["key"]: c["label"] for c in head}
    per: dict[str, list[dict[str, Any]]] = {}
    for (a, b), ts in edges.items():
        for x, y in ((a, b), (b, a)):
            per.setdefault(x, []).append({"key": y, "label": label[y], "shared": len(ts), "title": ts[0]})
    for k in per:
        per[k] = sorted(per[k], key=lambda e: -e["shared"])[:LINKS_PER_ITEM]
    # connected groups (union-find), largest first
    parent = {k: k for k in label}

    def root(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for a, b in edges:
        parent[root(a)] = root(b)
    comps: dict[str, list[str]] = {}
    for k in label:
        comps.setdefault(root(k), []).append(k)
    order = {c["key"]: i for i, c in enumerate(head)}
    groups = []
    for members in comps.values():
        if len(members) < 3:
            continue
        members.sort(key=order.get)
        inner = [ts for (a, b), ts in edges.items() if a in members and b in members]
        groups.append({"keys": members, "labels": [label[k] for k in members],
                       "edges": len(inner), "title": min((t[0] for t in inner), key=len)})
    groups.sort(key=lambda g: (-len(g["keys"]), order[g["keys"][0]]))
    return per, groups


# --- 작년 이맘때 ---------------------------------------------------------------------------
def season(series: list[tuple[date, int]], today: date) -> dict[str, Any] | None:
    """Daily views of the issue's encyclopedia article: is this a yearly visitor or new?"""
    by_day = dict(series)
    recent = [by_day.get(today - timedelta(days=k), 0) for k in range(SEASON_RECENT)]
    if max(recent) <= 0:
        return None
    ago = today - timedelta(days=365)
    window = [by_day[ago + timedelta(days=k)] for k in range(-SEASON_SLACK, SEASON_SLACK + 1)
              if ago + timedelta(days=k) in by_day]
    if len(window) <= SEASON_SLACK:
        return None  # the series doesn't reach back a year
    older = [v for d, v in series if d <= ago + timedelta(days=SEASON_SLACK)]
    usual = statistics.median([v for d, v in series if d < today - timedelta(days=SEASON_RECENT)] or [0])
    peak, last = max(recent), max(window)
    lift = peak / usual if usual > 0 else None
    if not any(older):
        label = "작년엔 문서가 없던 새 관심"
    elif lift is not None and lift < USUAL_LIFT:
        label = "평소와 비슷한 관심 (늘 보는 문서)"
    elif last >= SEASON_RECUR * peak:
        label = "매년 이맘때 오는 관심"
    elif last < SEASON_NEW * peak:
        label = "작년 이맘때는 조용했음"
    else:
        label = "작년에도 조금 있었음"
    return {"label": label, "recent_peak": peak, "last_year_peak": last,
            "times_usual": round(lift, 1) if lift is not None else None}


# --- 합치기 ---------------------------------------------------------------------------------
def build(report: dict[str, Any], snapshots: list[dict[str, Any]], rows: dict[str, list[dict[str, Any]]],
          seasons: dict[str, dict[str, Any]], top: int = 40) -> dict[str, Any]:
    clusters = report.get("clusters", [])[:top]
    per_links, groups = links(clusters)
    items: dict[str, dict[str, Any]] = {}
    origins = []
    for c in clusters:
        o = origin(c, snapshots)
        origins.append(o)
        entry = {"why": why(c), "origin": o, "life": life(rows.get(c["key"], []), report["generated_at"]),
                 "links": per_links.get(c["key"], []), "season": seasons.get(c["key"])}
        items[c["key"]] = {k: v for k, v in entry.items() if v}
    window = (_ts(report["generated_at"]) - _ts(snapshots[0]["generated_at"])).total_seconds() / 3600 if snapshots else 0
    return {"region": report["region"], "generated_at": report["generated_at"], "items": items,
            "leads": leads(origins), "groups": groups[:6], "origin_hours": round(window)}
