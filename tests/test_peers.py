"""비슷한 관심 레벨 이웃 고르기."""

from trend_engine.peers import attach_peers, similar_level


def _row(label, score, category="기타", key=None):
    return {"label": label, "key": key or label, "score": score, "category": category}


def test_prefers_same_category_and_nearby_score():
    items = [
        _row("A", 200, "음악"),
        _row("B", 190, "음악"),
        _row("C", 50, "게임"),
        _row("D", 185, "스포츠"),
    ]
    peers = similar_level(items, 0, limit=3)
    assert [p["label"] for p in peers][:2] == ["B", "D"]  # B same cat + close score, D close score
    assert peers[0]["same_category"] is True and peers[0]["why"] == "같은 분야 · 비슷한 점수"


def test_rank_window_catches_neighbors_even_if_scores_diverge():
    items = [_row("1위", 300), _row("2위", 40), _row("먼곳", 39)]
    peers = similar_level(items, 0, score_tol=0.1, rank_window=1, limit=2)
    assert [p["label"] for p in peers] == ["2위"]
    assert peers[0]["why"] == "근처 순위"


def test_attach_peers_in_place():
    items = [_row("x", 10, "음식"), _row("y", 11, "음식"), _row("z", 3, "테크·IT")]
    attach_peers(items, limit=2)
    assert items[0]["peers"][0]["label"] == "y"
    assert items[1]["peers"][0]["label"] == "x"
