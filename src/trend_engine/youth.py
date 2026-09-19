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
# Empirical-Bayes shrinkage instead of a hard volume cut-off: rare queries swing age ratios wildly
# ("발로란트 강의 131배"), so a ratio is pulled toward 1× in proportion to how little data backs it:
#   w = V / (V + K),  shrunk = raw ** w      (V = overall volume as % of the anchor '날씨')
# K = 0.05% (≈ '등산'): a keyword with that much volume keeps half of its log-ratio.
SHRINK_K = 0.05
MIN_RELATIVE_PCT = 0.002  # below this there is essentially no data at all


def shrink(ratio: float, volume_pct: float | None, k: float = SHRINK_K) -> float:
    """Pull a ratio (1.0 = no difference) toward 1 by the evidence weight w = V/(V+K)."""
    if volume_pct is None or ratio <= 0:
        return ratio
    w = volume_pct / (volume_pct + k)
    return ratio ** w
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


def candidate_categories(kinds: dict[str, str], report: dict[str, Any], shopping: dict[str, Any] | None) -> dict[str, str]:
    """Category per candidate from where it came from; the classifier's lexicon/video votes as fallback."""
    from . import categories as cat

    by_query: dict[str, str] = {}
    for c in report.get("clusters", []):
        if c.get("category"):
            by_query[norm_key(c.get("query") or c["label"])] = c["category"]
            by_query.setdefault(norm_key(c["label"]), c["category"])
    videos = [v for items in report.get("content", {}).values() for v in items
              if v.get("kind") == "content" and v.get("category")]
    shop = cat.shopping_index(shopping)
    out: dict[str, str] = {}
    for term, kind in kinds.items():
        k = norm_key(term)
        found = None
        if kind == "이슈":
            found = by_query.get(k)
        elif kind == "콘텐츠":
            v = next((v for v in videos if k in {norm_key(t) for t in v.get("related", [])}), None)
            found = cat.VIDEO_CATEGORIES.get(v["category"]) if v else None
        elif kind == "쇼핑" and k in shop:
            found = cat.SHOPPING_CATEGORIES.get(shop[k])
        if not found or found == "기타":
            found = cat.classify([term], [], {}, videos, {}, shop)[0]
        out[term] = found
    return out


def youth_view(profile: dict[str, Any], kinds: dict[str, str] | None = None, labels: dict[str, str] | None = None,
               min_affinity: float = MIN_AFFINITY, min_vs_older: float = MIN_VS_OLDER, limit: int = 15,
               cats: dict[str, str] | None = None) -> dict[str, Any]:
    """Turn a segment profile (must include OLDER) into per-group youth rankings."""
    aff = profile["affinity"]
    rel = profile.get("relative", {})
    kinds, labels, cats = kinds or {}, labels or {}, cats or {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for g in YOUTH_GROUPS:
        rows = []
        for k, by_seg in aff.items():
            a, older = by_seg.get(g), by_seg.get(OLDER)
            if a is None or not older or len(norm_key(labels.get(k, k))) < 2:
                continue
            overall = rel.get(k, {}).get("전체")
            if overall is not None and overall < MIN_RELATIVE_PCT:
                continue
            raw = a / older
            vs = shrink(raw, overall)
            aff_s = 100 * shrink(a / 100, overall)
            if aff_s >= min_affinity and vs >= min_vs_older:
                rows.append({"keyword": labels.get(k, k), "affinity": round(aff_s, 1), "vs_older": round(vs, 1),
                             "vs_raw": round(raw, 1), "kind": kinds.get(k, ""), "category": cats.get(k, "기타")})
        rows.sort(key=lambda r: (-r["vs_older"], -r["affinity"]))
        groups[g] = rows[:limit]
    return {"period": profile.get("period"), "groups": groups, "synthetic": profile.get("synthetic", False)}


async def discover(settings, store, report: dict[str, Any], shopping: dict[str, Any] | None) -> dict[str, Any]:
    kinds = candidates(report, shopping)
    prof = SegmentProfiler(settings, store)
    result = await prof.profile(list(kinds), [parse_segment(g) for g in [*YOUTH_GROUPS, OLDER]])
    view = youth_view(result.to_dict(), kinds, cats=candidate_categories(kinds, report, shopping))
    view["candidates"] = len(kinds)
    return view


def issue_view(segments: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Today's issues ranked by how much more each youth group cares than 30대 이상."""
    kinds = {k: "이슈" for k in segments.get("keywords", [])}
    cats = candidate_categories(kinds, report, None) if report else None
    return youth_view(segments, kinds, segments.get("labels"), min_affinity=100.0, min_vs_older=1.2, limit=10, cats=cats)
