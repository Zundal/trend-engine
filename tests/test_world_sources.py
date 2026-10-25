"""미국·영국·대만·베트남 로컬 소스 parse — fixture 기반, 네트워크 없음."""

from pathlib import Path

import pytest

from trend_engine.sources import REGISTRY

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(("name", "code", "at_least"), [
    ("billboard_us", "US", 40), ("yahoo_us", "US", 8), ("official_charts", "GB", 40), ("bbc_news", "GB", 10),
    ("kkbox_tw", "TW", 40), ("yahoo_tw_search", "TW", 8), ("yahoo_tw", "TW", 10), ("gnn_tw", "TW", 10), ("vnexpress", "VN", 10), ("tuoitre", "VN", 20), ("dantri", "VN", 20), ("thanhnien", "VN", 20),
])
def test_country_source_parses_its_fixture(name, code, at_least):
    src = REGISTRY[name]
    items = src.parse((FIX / name / f"{code}.{src.fixture_ext}").read_text(encoding="utf-8"), code)
    assert len(items) >= at_least
    assert [i.rank for i in items] == list(range(1, len(items) + 1))
    assert all(i.keyword and "<" not in i.keyword for i in items)
    assert src.regions == frozenset({code})


def test_taiwan_hot_search_drops_paid_terms():
    src = REGISTRY["yahoo_tw_search"]
    raw = (FIX / "yahoo_tw_search" / "TW.html").read_text(encoding="utf-8")
    items = src.parse(raw, "TW")
    assert items and all(i.kind == "keyword" for i in items)
    assert raw.count("kt:rev") >= 1
    assert not any(f"tts-term:{i.keyword};" in seg and "kt:rev" in seg
                   for i in items for seg in raw.split("data-ylk=")[1:])


def test_music_charts_carry_artist_and_skip_legend_text():
    for name, code in (("billboard_us", "US"), ("official_charts", "GB"), ("kkbox_tw", "TW")):
        src = REGISTRY[name]
        items = src.parse((FIX / name / f"{code}.{src.fixture_ext}").read_text(encoding="utf-8"), code)
        assert all(i.meta.get("artist") for i in items[:10]), name
        assert not any("Weekly Performance" in i.keyword or "Songwriter" in i.keyword for i in items), name
