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


def test_novelty_demotes_every_day_regulars():
    from trend_engine.scoring import apply_novelty
    items = [kw("wikipedia", 1, "문화방송"), kw("google_trends", 1, "새 이슈")]
    clusters = build_clusters(items, [], {"wikipedia": 1.0, "google_trends": 1.0})
    days = {f"d{i}" for i in range(10)}
    out = apply_novelty(clusters, {"문화방송": days}, history_days=10)
    assert [c.label for c in out] == ["새 이슈", "문화방송"]
    regular = out[1]
    assert (regular.days_seen, regular.novelty, regular.score) == (10, 0.0, 40.0)  # 100 × (1 - 0.6)
    assert out[0].novelty == 1.0 and out[0].score == 100.0


def test_novelty_waits_for_enough_history():
    from trend_engine.scoring import apply_novelty
    [c] = apply_novelty(build_clusters([kw("wikipedia", 1, "문화방송")], [], {"wikipedia": 1.0}), {"문화방송": {"d1"}}, 2)
    assert c.novelty is None and c.score == 100.0 and c.days_seen == 1


def _theme_labels(clusters, content):
    from trend_engine.scoring import build_themes
    return [[m.label for m in t.members] for t in build_themes(clusters, content)]


def test_themes_merge_the_same_story_but_not_lookalikes():
    from trend_engine.scoring import build_themes
    items = [kw("google_trends", 1, "아이치 나고야 아시안게임 개막"), kw("google_trends", 2, "나고야"),
             kw("google_trends", 3, "아이폰16"), kw("google_trends", 4, "아이폰17"),
             kw("nate", 1, "마크"), kw("nate", 2, "마크롱")]
    clusters = build_clusters(items, [], W)
    groups = _theme_labels(clusters, [])
    assert ["아이치 나고야 아시안게임 개막", "나고야"] in groups  # whole-word containment
    assert all(len(g) == 1 for g in groups if g[0] in ("아이폰16", "아이폰17", "마크", "마크롱"))


def test_themes_merge_two_entities_that_share_a_headline():
    from trend_engine.scoring import build_themes
    head = [content("google_news", 1, "손흥민 토트넘 복귀전 골")]
    items = [kw("google_trends", 1, "손흥민"), kw("google_trends", 2, "토트넘")]
    clusters = build_clusters(items, head, W)
    assert len(clusters) == 2  # different words: the keyword clusterer keeps them apart
    themes = build_themes(clusters, head)
    assert len(themes) == 1 and [m.label for m in themes[0].members] == ["손흥민", "토트넘"]
    assert themes[0].score == round(clusters[0].score + 0.25 * clusters[1].score, 1)
    assert themes[0].label == clusters[0].label  # strongest member names the theme


def test_theme_takes_a_real_category_from_any_member():
    from trend_engine.scoring import build_themes
    a, b = build_clusters([kw("google_trends", 1, "나고야 아시안게임"), kw("google_trends", 2, "나고야")], [], W)
    a.category, b.category = "기타", "스포츠"
    assert build_themes([a, b], [])[0].category == "스포츠"
