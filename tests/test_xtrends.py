from pathlib import Path

import pytest

from trend_engine.sources import REGISTRY
from trend_engine.sources.xtrends import X_FAMILY

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(("name", "country"), [("trends24", "JP"), ("getdaytrends", "US"), ("getdaytrends", "GB")])
def test_x_trend_lists_parse(name, country):
    src = REGISTRY[name]
    items = src.parse((FIX / name / f"{country}.html").read_text(encoding="utf-8"), country)
    assert 10 <= len(items) <= src.LIMIT
    assert [i.rank for i in items] == list(range(1, len(items) + 1))
    terms = [i.keyword for i in items]
    assert all(not t.startswith("#") and "_" not in t for t in terms)
    assert len({t.lower() for t in terms}) == len(terms)


def test_trends24_strips_hashtag_and_keeps_flag():
    raw = ("<ol class=trend-card__list><li><a href=x class=trend-link>#Big_Game</a></li>"
           "<li><a href=y class=trend-link>big game</a></li><li><a href=z class=trend-link>Texas</a></li></ol>"
           "<ol class=trend-card__list><li><a href=w class=trend-link>Older</a></li></ol>")
    items = REGISTRY["trends24"].parse(raw, "US")
    assert [(i.keyword, i.meta["hashtag"]) for i in items] == [("Big Game", True), ("Texas", False)]


def test_yahoo_realtime_ordered_by_position():
    items = REGISTRY["yahoo_realtime"].parse((FIX / "yahoo_realtime" / "JP.html").read_text(encoding="utf-8"), "JP")
    assert len(items) == 20
    assert items[0].keyword == "中村公晴"
    assert all("%" not in i.keyword for i in items)


def test_x_sources_share_family_and_skip_fan_hashtag_regions():
    t24, gdt, yr = REGISTRY["trends24"], REGISTRY["getdaytrends"], REGISTRY["yahoo_realtime"]
    assert t24.family == gdt.family == yr.family == X_FAMILY
    assert t24.regions == {"JP"} and gdt.regions == {"US", "GB"} and yr.regions == {"JP"}


def test_getdaytrends_skips_top_hashtags_table():
    raw = ('<table class="table ranking trends wider mb-0"><tr><td><a class="string" href="/a/">Lula</a></td></tr></table>'
           '<table class="table ranking trends wider collapse" id="moreTrends"><tr><td><a class="string" href="/b/">Chiefs</a></td></tr></table>'
           '<table class="table ranking top mb-0"><tr><td><a class="string" href="/c/">#OldTag</a></td></tr></table>')
    assert [i.keyword for i in REGISTRY["getdaytrends"].parse(raw, "US")] == ["Lula", "Chiefs"]


@pytest.mark.parametrize(("country", "first"), [("GB", "Michael Carrick"), ("US", "Venezuelan opposition leader returns home after months in exile")])
def test_yahoo_trending_reads_ranked_terms_once(country, first):
    items = REGISTRY["yahoo_trending"].parse((FIX / "yahoo_trending" / f"{country}.html").read_text(encoding="utf-8"), country)
    assert items[0].keyword == first
    assert len(items) == len({i.keyword for i in items}) >= 5
    assert "Trending" not in [i.keyword for i in items]


def test_zum_issue_reads_embedded_issue_words():
    src = REGISTRY["zum_issue"]
    items = src.parse((FIX / "zum_issue" / "KR.html").read_text(encoding="utf-8"), "KR")
    assert len(items) >= 10
    assert all("\\u" not in i.keyword and '"' not in i.keyword for i in items)
    assert all(i.meta["state"].isupper() for i in items)
    assert src.family != REGISTRY["nate"].family
