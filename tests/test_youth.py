"""10·20대 focus: candidate pooling and the 'vs 30대 이상' youth ranking."""

import pytest

from trend_engine import youth
from trend_engine.config import Settings
from trend_engine.segments import OLDER, YOUTH_GROUPS


def test_candidates_pool_issues_video_tags_and_youth_shopping():
    report = {
        "clusters": [{"label": "청하 응급실", "query": "청하"}, {"label": "전투기", "query": "전투기"}],
        "content": {
            "youtube": [
                {"kind": "content", "related": ["#아일릿", "ILLIT", "Official", "MV"]},
                {"kind": "content", "related": ["아일릿", "Magnetic"]},
                {"kind": "content", "related": ["123", "Shorts"]},
            ],
            "google_news": [{"kind": "content", "related": []}],
        },
    }
    shopping = {"by_segment": {"10대": {"패션의류": {"top": ["후드집업", "져지"], "distinctive": ["져지"]}},
                               "60대+": {"식품": {"top": ["사과"], "distinctive": ["사과"]}}}}
    c = youth.candidates(report, shopping)
    assert c["청하"] == "이슈" and c["전투기"] == "이슈"
    assert c["아일릿"] == "콘텐츠" and "ILLIT" in c
    assert c["져지"] == "쇼핑"
    assert "사과" not in c  # 60대+ shopping is not a youth candidate
    for junk in ("Official", "MV", "123", "Shorts", "#아일릿"):
        assert junk not in c


def test_youth_view_requires_both_affinity_and_gap_vs_older():
    aff = {
        "아일릿": {"10대": 400.0, "20대": 200.0, OLDER: 50.0},     # strongly young
        "등산": {"10대": 60.0, "20대": 80.0, OLDER: 130.0},        # older interest
        "아이폰": {"10대": 130.0, "20대": 125.0, OLDER: 110.0},    # everyone (gap < 1.5)
    }
    for k in aff:
        for g in YOUTH_GROUPS:
            aff[k].setdefault(g, None)
    v = youth.youth_view({"affinity": aff, "period": ["a", "b"]}, {"아일릿": "콘텐츠"})
    assert [r["keyword"] for r in v["groups"]["10대"]] == ["아일릿"]
    top = v["groups"]["10대"][0]
    assert top == {"keyword": "아일릿", "affinity": 400.0, "vs_older": 8.0, "kind": "콘텐츠"}
    assert v["groups"]["20대"][0]["vs_older"] == 4.0
    assert v["groups"]["10대 여성"] == []  # no data -> empty, not an error


async def test_discover_profiles_candidates_with_youth_and_older_segments(monkeypatch):
    seen = {}

    async def fake_profile(self, keywords, segments):
        seen["keywords"], seen["segments"] = keywords, [s.name for s in segments]
        from trend_engine.segments import SegmentResult
        aff = {k: {g: (300.0 if g in ("10대", "20대") else None) for g in YOUTH_GROUPS} | {OLDER: 100.0} for k in keywords}
        return SegmentResult(keywords, seen["segments"], aff, {}, {}, "날씨", ("s", "e"))

    monkeypatch.setattr(youth.SegmentProfiler, "profile", fake_profile)
    report = {"clusters": [{"label": "청하", "query": "청하"}], "content": {}}
    v = await youth.discover(Settings(), None, report, None)
    assert seen["segments"] == [*YOUTH_GROUPS, OLDER]
    assert v["candidates"] == 1 and v["groups"]["10대"][0]["vs_older"] == 3.0


@pytest.mark.parametrize("group", YOUTH_GROUPS)
def test_every_youth_group_has_shopping_and_search_segment(group):
    from trend_engine.segments import parse_segment
    from trend_engine.shopping import SEGMENTS
    assert group in SEGMENTS
    parse_segment(group)
