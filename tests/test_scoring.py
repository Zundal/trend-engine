"""Golden tests for merge + score semantics (see scoring.py docstring)."""

from trend_engine.models import TrendCluster, TrendItem
from trend_engine.scoring import build_clusters

W = {"google_trends": 1.0, "signal_bz": 0.9, "nate": 0.9, "wikipedia": 0.4, "youtube": 0.6}
FAM = {"signal_bz": "portal", "nate": "portal"}


def kw(source, rank, keyword, **meta):
    return TrendItem(source=source, region="KR", rank=rank, keyword=keyword, meta=meta)


def content(source, rank, title):
    return TrendItem(source=source, region="KR", rank=rank, keyword=title, kind="content")


def test_cross_source_merge_and_consensus():
    items = [kw("google_trends", 1, "두산에너 빌리티"), kw("google_trends", 2, "청하"),
             kw("signal_bz", 1, "두산에너빌리티")]
    clusters = build_clusters(items, [], W, families=FAM)
    top = clusters[0]
    assert top.sources == {"google_trends": 1, "signal_bz": 1}
    # (1.0 + 0.9) * (1 + 0.3) * 100
    assert top.score == 247.0
    assert clusters[1].label == "청하"


def test_correlated_family_is_not_double_counted():
    items = [kw("signal_bz", 1, "화재"), kw("nate", 1, "화재")]
    [c] = build_clusters(items, [], W, families=FAM)
    # max(0.9) + 0.25*0.9, no consensus bonus (same family)
    assert c.score == 112.5


def test_content_mentions_boost():
    items = [kw("google_trends", 1, "청하"), kw("google_trends", 2, "전투기")]
    vids = [content("youtube", 1, "청하 직캠"), content("youtube", 2, "먹방")]
    clusters = build_clusters(items, vids, W)
    assert clusters[0].mentions == {"youtube": ["청하 직캠"]}
    assert clusters[0].score == 112.0  # (1.0 + 0.6*1/5) * 100


def test_query_prefers_short_search_form():
    items = [kw("nate", 1, "김성수 대법관 임명 재가", query="김성수 대법관")]
    [c] = build_clusters(items, [], W)
    assert c.query == "김성수 대법관"


def test_history_status():
    items = [kw("google_trends", 1, "A키워드"), kw("google_trends", 2, "B키워드"), kw("google_trends", 3, "신규")]
    prev = [TrendCluster(label="B키워드", key="b키워드", score=1, query="B키워드"),
            TrendCluster(label="A키워드", key="a키워드", score=1, query="A키워드")]
    a, b, new = build_clusters(items, [], W, previous=prev)
    assert (a.status, a.rank_change) == ("rising", 1)
    assert (b.status, b.rank_change) == ("falling", -1)
    assert new.status == "new"


def test_deterministic():
    items = [kw("google_trends", i, f"키워드{i}") for i in range(1, 11)]
    assert [c.to_dict() for c in build_clusters(items, [], W)] == [c.to_dict() for c in build_clusters(items, [], W)]
