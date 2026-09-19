"""Alerts fire on change only, carry no source names, and render as valid RSS."""

from datetime import datetime, timezone

from defusedxml import ElementTree as ET

from trend_engine import alerts as al


def tracked(stage="확산 대기", keyword="로블록스", **extra):
    return {"items": [{"keyword": keyword, "stage": stage, "category": "게임", "old_lag_weeks": None} | extra]}


def youth(vs=2.5, keyword="로블록스"):
    return {"groups": {"10대": [{"keyword": keyword, "vs_older": vs}]}}


def test_watchlist_parsing(tmp_path):
    p = tmp_path / "watchlist.txt"
    p.write_text("# 주석\n탕후루\n\n  로블록스  # 인라인 주석\n", encoding="utf-8")
    assert al.load_watchlist(p) == ["탕후루", "로블록스"]
    assert al.load_watchlist(tmp_path / "nope.txt") == []


def test_alerts_fire_once_per_change():
    first, state = al.evaluate(tracked(), youth(), None, [], "2026-09-20")
    kinds = {a.kind for a in first}
    assert kinds == {"stage", "youth"} and all(a.keyword == "로블록스" for a in first)
    again, state2 = al.evaluate(tracked(), youth(), state, [], "2026-09-21")
    assert again == []  # nothing changed -> silence
    moved, _ = al.evaluate(tracked("확산 중", old_lag_weeks=3), youth(), state2, [], "2026-09-22")
    assert [a.kind for a in moved] == ["stage"] and "3주" in moved[0].message


def test_watchlist_keywords_are_marked_and_first_seen():
    alerts, _ = al.evaluate(tracked(keyword="탕후루"), None, None, ["탕후루"], "2026-09-20")
    assert all(a.watched for a in alerts)
    assert any(a.kind == "watchlist" for a in alerts)


def test_forecast_alert_only_when_peak_is_near():
    now = tracked(forecast={"ages": {"40대": {"weeks_from_now": 0}}})  # already peaking: not a forecast
    assert not any(a.kind == "forecast" for a in al.evaluate(now, None, None, [], "2026-09-20")[0])
    near = tracked(forecast={"ages": {"40대": {"weeks_from_now": 3}}})
    far = tracked(forecast={"ages": {"40대": {"weeks_from_now": 20}}})
    assert any(a.kind == "forecast" for a in al.evaluate(near, None, None, [], "2026-09-20")[0])
    assert not any(a.kind == "forecast" for a in al.evaluate(far, None, None, [], "2026-09-20")[0])


def test_merge_recent_dedupes_and_trims():
    a1, _ = al.evaluate(tracked(), None, None, [], "2026-09-20")
    merged = al.merge_recent(a1, [])
    assert al.merge_recent(a1, merged) == merged  # same alerts again -> no growth
    old = [{"id": "x", "date": "2026-01-01", "kind": "stage", "keyword": "옛것", "category": "", "message": "m"}]
    assert al.merge_recent([], old + merged, keep_days=1) == [a for a in merged if a["date"] == "2026-09-20"]


def test_rss_is_valid_and_source_free():
    alerts, _ = al.evaluate(tracked(), youth(), None, ["로블록스"], "2026-09-20")
    xml = al.to_rss([a.to_dict() for a in alerts], "https://example.test/", datetime(2026, 9, 20, tzinfo=timezone.utc))
    root = ET.fromstring(xml)
    items = root.findall("./channel/item")
    assert len(items) == len(alerts)
    assert items[0].findtext("title") and items[0].findtext("guid")
    assert "example.test" in items[0].findtext("link")
    assert not al.SOURCE_WORDS.search(xml)
