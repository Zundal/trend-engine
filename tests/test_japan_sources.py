"""일본 전용 소스 parse 스모크 — fixture 기반, 네트워크 없음."""

from pathlib import Path

from trend_engine.sources.japan import BillboardJapan, Hatena, LivedoorTrend, NicoVideo, YahooTopics

FIX = Path(__file__).parent / "fixtures"


def _raw(name: str, ext: str) -> str:
    return (FIX / name / f"JP.{ext}").read_text(encoding="utf-8")


def test_yahoo_topics_dedupes_across_feeds():
    items = YahooTopics().parse(_raw("yahoo_topics", "json"), "JP")
    assert len(items) >= 20
    assert items[0].kind == "keyword" and items[0].rank == 1
    assert len({it.keyword for it in items}) == len(items)
    spaced = [it for it in items if " " in it.keyword]
    assert spaced and all(it.query == it.keyword.split()[0] for it in spaced)  # topic head doubles as the search query


def test_hatena_reads_rdf_rss():
    items = Hatena().parse(_raw("hatena", "xml"), "JP")
    assert len(items) >= 10 and items[0].url and items[0].kind == "content"


def test_nicovideo_ranking_json():
    items = NicoVideo().parse(_raw("nicovideo", "json"), "JP")
    assert len(items) == 30 and items[0].url and items[0].volume


def test_billboard_japan_hot100():
    items = BillboardJapan().parse(_raw("billboard_japan", "html"), "JP")
    assert len(items) >= 40 and items[0].meta.get("artist")


def test_livedoor_trend_rss():
    items = LivedoorTrend().parse(_raw("livedoor_trend", "xml"), "JP")
    assert len(items) >= 8 and items[0].category == "토픽"
