"""Merge TrendItems from many sources into ranked TrendClusters.

score = (Σ_family strength + Σ_content weight·mention_ratio) × consensus × 100
  strength       = weight · rank_score,  rank_score = 1 - (rank-1)/n   (1.0 for #1)
  family         = correlated sources (signal.bz & Nate both mirror portal issue keywords):
                   family strength = max + 0.25 × rest, so echoes don't count as confirmation
  mention_ratio  = min(mentions, 5) / 5       # YouTube titles / news headlines mentioning it
  consensus      = 1 + 0.3 × (independent families - 1)

Deterministic and pure — covered by golden tests in tests/test_scoring.py.
"""

from __future__ import annotations

from collections import defaultdict

from .models import TrendCluster, TrendItem, TrendTheme
from .normalize import mentions_any, norm_key, similar, similar_text, tokens

CONSENSUS_BONUS = 0.3
FAMILY_ECHO = 0.25
MENTION_CAP = 5


def _rank_score(item: TrendItem, n: int) -> float:
    return 1 - (item.rank - 1) / max(n, 1)


class _Draft:
    def __init__(self, item: TrendItem):
        self.items: list[TrendItem] = [item]
        self.texts: set[str] = {t for t in (item.keyword, item.query) if norm_key(t)}
        self.keys: set[str] = {norm_key(t) for t in self.texts}

    def matches(self, item: TrendItem) -> bool:
        return any(similar_text(a, b) for a in self.texts for b in (item.keyword, item.query) if norm_key(b))

    def add(self, item: TrendItem) -> None:
        self.items.append(item)
        new = {t for t in (item.keyword, item.query) if norm_key(t)}
        self.texts |= new
        self.keys |= {norm_key(t) for t in new}


def build_clusters(
    keyword_items: list[TrendItem],
    content_items: list[TrendItem],
    weights: dict[str, float],
    previous: list[TrendCluster] | None = None,
    limit: int = 50,
    families: dict[str, str] | None = None,
) -> list[TrendCluster]:
    families = families or {}
    counts: dict[str, int] = defaultdict(int)
    for it in keyword_items:
        counts[it.source] += 1

    def item_strength(it: TrendItem) -> float:
        return weights.get(it.source, 1.0) * _rank_score(it, counts[it.source])

    drafts: list[_Draft] = []
    for it in sorted(keyword_items, key=item_strength, reverse=True):
        if not norm_key(it.keyword):
            continue
        for d in drafts:
            if d.matches(it):
                d.add(it)
                break
        else:
            drafts.append(_Draft(it))

    clusters: list[TrendCluster] = []
    for d in drafts:
        best: dict[str, TrendItem] = {}
        for it in d.items:
            if it.source not in best or it.rank < best[it.source].rank:
                best[it.source] = it
        by_family: dict[str, list[float]] = defaultdict(list)
        for src, it in best.items():
            by_family[families.get(src, src)].append(item_strength(it))
        base = sum(max(v) + FAMILY_ECHO * (sum(v) - max(v)) for v in by_family.values())

        mentioned: dict[str, list[str]] = defaultdict(list)
        for c in content_items:
            if mentions_any(d.texts, c.keyword):
                mentioned[c.source].append(c.keyword)
        content_boost = sum(
            weights.get(src, 0.5) * min(len(titles), MENTION_CAP) / MENTION_CAP
            for src, titles in mentioned.items()
        )
        consensus = 1 + CONSENSUS_BONUS * (len(by_family) - 1)
        lead = d.items[0]
        queries = sorted({it.query for it in d.items if len(norm_key(it.query)) >= 2}, key=len)
        related: list[str] = []
        for it in d.items:
            for r in it.related:
                if r not in related:
                    related.append(r)
        volumes = [it.volume for it in d.items if it.source == "google_trends" and it.volume]
        clusters.append(
            TrendCluster(
                label=lead.keyword,
                key=norm_key(lead.keyword),
                score=round((base + content_boost) * consensus * 100, 1),
                variants=sorted({it.keyword for it in d.items}),
                sources={s: it.rank for s, it in sorted(best.items())},
                mentions={k: v[:5] for k, v in mentioned.items()},
                related=related[:6],
                query=queries[0] if queries else lead.keyword,
                volume=max(volumes) if volumes else None,
            )
        )

    clusters.sort(key=lambda c: (-c.score, c.label))
    clusters = clusters[:limit]
    if previous is not None:
        apply_history(clusters, previous)
    return clusters


THEME_ECHO = 0.25  # extra members add a quarter of their score to the theme


def _same_story(a: TrendCluster, b: TrendCluster, titles: list[set[str]]) -> bool:
    """Only merge on evidence: one is a whole word of the other, or both appear in one headline/video
    title, or they share a related article. (Plain character overlap would merge 마크 / 마크롱.)"""
    ta = set().union(*(tokens(x) for x in [a.label, a.query, *a.variants])) or {a.key}
    tb = set().union(*(tokens(x) for x in [b.label, b.query, *b.variants])) or {b.key}
    if (ta <= tb or tb <= ta) and min(len(ta), len(tb)) >= 1:
        return True
    if set(a.related) & set(b.related):
        return True
    return any(ta & t and tb & t for t in titles)


def build_themes(clusters: list[TrendCluster], content_items: list[TrendItem], limit: int = 30) -> list[TrendTheme]:
    """Group clusters that tell the same story; the strongest member names the theme."""
    titles = [tokens(c.keyword) for c in content_items]
    themes: list[TrendTheme] = []
    for c in clusters:  # clusters arrive strongest-first
        for t in themes:
            if any(_same_story(c, m, titles) for m in t.members):
                t.members.append(c)
                break
        else:
            themes.append(TrendTheme(label=c.label, key=c.key, score=c.score, members=[c],
                                     category=c.category, status=c.status, rank_change=c.rank_change))
    for t in themes:
        rest = sum(m.score for m in t.members[1:])
        t.score = round(t.members[0].score + THEME_ECHO * rest, 1)
        cats = [m.category for m in t.members if m.category and m.category != "기타"]
        t.category = cats[0] if cats else t.members[0].category
    themes.sort(key=lambda t: (-t.score, t.label))
    return themes[:limit]


NOVELTY_WEIGHT = 0.6  # an every-day regular keeps 40% of its score
NOVELTY_MIN_DAYS = 3  # need this many past days of history before novelty kicks in


def apply_novelty(clusters: list[TrendCluster], seen_days: dict[str, set], history_days: int) -> list[TrendCluster]:
    """Demote evergreen interests (방송사 wiki pages, 날씨, 상시 게임) by how many of the past days they
    were already in the ranking: score × (1 - 0.6 × familiarity). Re-sorted; pure."""
    for c in clusters:
        keys = {c.key, norm_key(c.query), *(norm_key(v) for v in c.variants)}
        days = set().union(*(seen_days.get(k, set()) for k in keys)) if keys else set()
        c.days_seen = len(days)
        if history_days >= NOVELTY_MIN_DAYS:
            familiarity = min(len(days) / history_days, 1.0)
            c.novelty = round(1 - familiarity, 2)
            c.score = round(c.score * (1 - NOVELTY_WEIGHT * familiarity), 1)
    return sorted(clusters, key=lambda c: (-c.score, c.label))


def apply_history(current: list[TrendCluster], previous: list[TrendCluster]) -> None:
    """Set status/rank_change by comparing with the previous snapshot's ranking."""
    for i, c in enumerate(current):
        prev_rank = next(
            (j for j, p in enumerate(previous) if similar(c.key, p.key) or similar(norm_key(c.query), norm_key(p.query))),
            None,
        )
        if prev_rank is None:
            c.status, c.rank_change = "new", None
        else:
            c.rank_change = prev_rank - i
            c.status = "rising" if c.rank_change > 0 else "steady" if c.rank_change == 0 else "falling"
