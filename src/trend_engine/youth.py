"""10·20대 focus: find what teens and people in their 20s search for *more than older people*.

Profiling only today's news trends misses youth interests (idols, games, products rarely hit the
general ranking). So we build a wider candidate pool, then let Korean search data by age decide:

  candidates = today's issues            (kind "이슈")
             + popular-video tags        (kind "콘텐츠": artists, games, shows)
             + 10·20대 shopping keywords (kind "쇼핑")

  for each youth group g (10대, 20대, 10대 여성 …):
      affinity_g(k)  — how much more group g searches k than the average (100 = average)
      vs_older_g(k)  = affinity_g(k) / affinity_30대이상(k)   — "30대 이상보다 몇 배"

A keyword is a youth interest for g when affinity_g ≥ 120 and vs_older_g ≥ 1.5.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .normalize import norm_key
from .segments import OLDER, YOUTH_GROUPS, SegmentProfiler, parse_segment

MAX_CANDIDATES = 40
MIN_AFFINITY = 120.0
MIN_VS_OLDER = 1.5
_JUNK = re.compile(r"^(\d+|shorts?|쇼츠|official|mv|m/v|live|vlog|브이로그|뉴스|news|하이라이트|highlight|예고편|trailer|full|ep\.?\s?\d+|\d+화)$", re.I)


def _ok(term: str) -> bool:
    t = term.strip().lstrip("#")
    return 2 <= len(t) <= 20 and not _JUNK.match(t) and len(norm_key(t)) >= 2


def candidates(report: dict[str, Any], shopping: dict[str, Any] | None, limit: int = MAX_CANDIDATES) -> dict[str, str]:
    """keyword -> kind. `report` is a raw engine report (content carries video tags in `related`)."""
    picked: dict[str, str] = {}
    seen: set[str] = set()

    def add(term: str, kind: str) -> None:
        term = term.strip().lstrip("#")
        key = norm_key(term)
        if _ok(term) and key not in seen:
            seen.add(key)
            picked[term] = kind

    for c in report.get("clusters", [])[:15]:
        add(c.get("query") or c["label"], "이슈")
    # video tags: keep tags that several popular videos share or that lead a video's tag list
    tags: Counter[str] = Counter()
    for items in report.get("content", {}).values():
        for v in items:
            if v.get("kind") != "content":
                continue
            for i, t in enumerate((v.get("related") or [])[:6]):
                tags[t.strip().lstrip("#")] += 2 if i < 2 else 1
    for t, _ in tags.most_common(20):
        add(t, "콘텐츠")
    if shopping:
        shop_terms: Counter[str] = Counter()
        for g in ("10대", "20대", "10대 여성", "10대 남성", "20대 여성", "20대 남성"):
            for v in shopping.get("by_segment", {}).get(g, {}).values():
                for t in v.get("distinctive", [])[:3]:
                    shop_terms[t] += 1
        for t, _ in shop_terms.most_common(15):
            add(t, "쇼핑")
    return dict(list(picked.items())[:limit])


def youth_view(profile: dict[str, Any], kinds: dict[str, str] | None = None, labels: dict[str, str] | None = None,
               min_affinity: float = MIN_AFFINITY, min_vs_older: float = MIN_VS_OLDER, limit: int = 15) -> dict[str, Any]:
    """Turn a segment profile (must include OLDER) into per-group youth rankings."""
    aff = profile["affinity"]
    kinds, labels = kinds or {}, labels or {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for g in YOUTH_GROUPS:
        rows = []
        for k, by_seg in aff.items():
            a, older = by_seg.get(g), by_seg.get(OLDER)
            if a is None or not older:
                continue
            vs = a / older
            if a >= min_affinity and vs >= min_vs_older:
                rows.append({"keyword": labels.get(k, k), "affinity": round(a, 1), "vs_older": round(vs, 1),
                             "kind": kinds.get(k, "")})
        rows.sort(key=lambda r: (-r["vs_older"], -r["affinity"]))
        groups[g] = rows[:limit]
    return {"period": profile.get("period"), "groups": groups, "synthetic": profile.get("synthetic", False)}


async def discover(settings, store, report: dict[str, Any], shopping: dict[str, Any] | None) -> dict[str, Any]:
    kinds = candidates(report, shopping)
    prof = SegmentProfiler(settings, store)
    result = await prof.profile(list(kinds), [parse_segment(g) for g in [*YOUTH_GROUPS, OLDER]])
    view = youth_view(result.to_dict(), kinds)
    view["candidates"] = len(kinds)
    return view


def issue_view(segments: dict[str, Any]) -> dict[str, Any]:
    """Today's issues ranked by how much more each youth group cares than 30대 이상."""
    return youth_view(segments, {k: "이슈" for k in segments.get("keywords", [])}, segments.get("labels"),
                      min_affinity=100.0, min_vs_older=1.2, limit=10)
