"""비슷한 관심 강도(점수·순위)·같은 분야의 이웃 트렌드를 고른다.

원재료(순위 목록)는 그대로 두고, **비슷한 레벨**을 읽을 수 있게 이웃만 붙인다.
순수 함수 — 네트워크·시계 없음.
"""

from __future__ import annotations

from typing import Any


def similar_level(
    items: list[dict[str, Any]],
    index: int,
    *,
    score_key: str = "score",
    score_tol: float = 0.35,
    rank_window: int = 8,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """`items[index]` 와 비슷한 레벨의 이웃 (가까운 점수·순위, 같은 분야 우선).

    반환: label/key/score/category/rank(1-based)/same_category/why
    """
    if not items or index < 0 or index >= len(items):
        return []
    me = items[index]
    my_score = float(me.get(score_key) or 0)
    my_cat = me.get("category") or "기타"
    my_key = me.get("key")
    cands: list[tuple[float, int, dict[str, Any], str]] = []
    for j, o in enumerate(items):
        if j == index or (my_key and o.get("key") == my_key):
            continue
        score = float(o.get(score_key) or 0)
        ratio = abs(score - my_score) / my_score if my_score > 0 else (0.0 if score == 0 else 1.0)
        rank_gap = abs(j - index)
        other_cat = o.get("category") or "기타"
        same_cat = my_cat != "기타" and other_cat == my_cat
        near_score = ratio <= score_tol
        near_rank = rank_gap <= rank_window
        if not (same_cat or near_score or near_rank):
            continue
        if same_cat and near_score:
            why = "같은 분야 · 비슷한 점수"
        elif same_cat:
            why = "같은 분야"
        elif near_score:
            why = "비슷한 점수대"
        else:
            why = "근처 순위"
        # 같은 분야·가까운 점수를 앞으로; 순위 거리는 약한 페널티
        dist = ratio + 0.04 * rank_gap - (0.45 if same_cat else 0.0) - (0.15 if near_score else 0.0)
        cands.append((dist, j, o, why))
    cands.sort(key=lambda t: (t[0], t[1]))
    out: list[dict[str, Any]] = []
    for _, j, o, why in cands[:limit]:
        out.append({
            "label": o["label"] if "label" in o else o.get("keyword", ""),
            "key": o.get("key") or o.get("keyword", ""),
            "score": round(float(o.get(score_key) or 0), 1),
            "category": o.get("category") or "기타",
            "rank": j + 1,
            "same_category": (o.get("category") or "기타") == my_cat and my_cat != "기타",
            "why": why,
        })
    return out


def attach_peers(
    items: list[dict[str, Any]],
    *,
    score_key: str = "score",
    limit: int = 4,
) -> list[dict[str, Any]]:
    """각 항목에 `peers` 필드를 붙여 반환 (원본 dict 는 복사하지 않고 in-place)."""
    for i, it in enumerate(items):
        it["peers"] = similar_level(items, i, score_key=score_key, limit=limit)
    return items
