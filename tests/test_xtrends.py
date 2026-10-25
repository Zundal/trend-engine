from pathlib import Path

import pytest

from trend_engine.sources import REGISTRY
from trend_engine.sources.xtrends import X_FAMILY

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("country", ["US", "JP", "GB"])
def test_trends24_reads_latest_list_only(country):
    src = REGISTRY["trends24"]
    items = src.parse((FIX / "trends24" / f"{country}.html").read_text(encoding="utf-8"), country)
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
    t24, yr = REGISTRY["trends24"], REGISTRY["yahoo_realtime"]
    assert t24.family == yr.family == X_FAMILY
    assert t24.regions == {"US", "JP", "GB"} and yr.regions == {"JP"}


def test_zum_issue_reads_embedded_issue_words():
    src = REGISTRY["zum_issue"]
    items = src.parse((FIX / "zum_issue" / "KR.html").read_text(encoding="utf-8"), "KR")
    assert len(items) >= 10
    assert all("\\u" not in i.keyword and '"' not in i.keyword for i in items)
    assert all(i.meta["state"].isupper() for i in items)
    assert src.family != REGISTRY["nate"].family
