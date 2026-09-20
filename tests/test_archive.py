"""History: daily KST summaries, durable archive files, weekly/monthly aggregation, pruning."""

import json
from datetime import date, datetime, timedelta, timezone

from trend_engine import archive
from trend_engine.store import Store

TODAY = date(2026, 9, 20)


def snap(store, when_kst: str, labels: list[str], region="KR"):
    """Save a report snapshot at a KST wall-clock time with clusters ranked in `labels` order."""
    t = datetime.fromisoformat(when_kst).replace(tzinfo=archive.KST).astimezone(timezone.utc)
    store.save_report({"region": region, "generated_at": t.isoformat(timespec="seconds"),
                       "clusters": [{"key": l.lower(), "label": l, "score": 100 - i * 10} for i, l in enumerate(labels)]})


def test_daily_summary_uses_kst_day_boundaries():
    s = Store(":memory:")
    snap(s, "2026-09-18T23:30", ["A", "B"])  # KST 9/18 (UTC 14:30 on 9/18)
    snap(s, "2026-09-19T00:30", ["B", "A"])  # KST 9/19 but still 9/18 in UTC
    snap(s, "2026-09-19T01:30", ["B", "C"])
    d18 = archive.daily_trends(s, "KR", date(2026, 9, 18))
    d19 = archive.daily_trends(s, "KR", date(2026, 9, 19))
    assert d18["snapshots"] == 1 and [k["label"] for k in d18["keywords"]] == ["A", "B"]
    assert d19["snapshots"] == 2
    b = next(k for k in d19["keywords"] if k["label"] == "B")
    assert (b["hours"], b["best_rank"], b["avg_score"]) == (2, 1, 100.0)


def test_finalize_writes_only_finished_days_once(tmp_path):
    s = Store(":memory:")
    snap(s, "2026-09-18T12:00", ["A"])
    snap(s, "2026-09-19T12:00", ["B"])
    snap(s, "2026-09-20T09:00", ["C"])  # today: not finalized
    archive.record_daily_extras(s, date(2026, 9, 19), {"top_by_segment": {"20대": []}, "labels": {}}, {"period": ["x", "y"], "by_segment": {}})
    archive.record_daily_extras(s, TODAY, {"top_by_segment": {}, "labels": {}}, None)
    written = archive.finalize(s, tmp_path, ["KR"], TODAY)
    assert sorted(written) == ["2026-09-18/trends-KR.json", "2026-09-19/segments.json",
                               "2026-09-19/shopping.json", "2026-09-19/trends-KR.json"]
    assert archive.finalize(s, tmp_path, ["KR"], TODAY) == []  # idempotent
    saved = json.loads((tmp_path / "2026-09-19" / "trends-KR.json").read_text())
    assert saved["keywords"][0]["label"] == "B" and "sources" not in saved["keywords"][0]


def test_period_trends_merges_archive_and_today(tmp_path):
    s = Store(":memory:")
    for day in (16, 17, 18, 19):
        snap(s, f"2026-09-{day}T10:00", ["Steady", f"Oneoff{day}"])
    snap(s, "2026-09-20T10:00", ["Fresh", "Steady"])
    archive.finalize(s, tmp_path, ["KR"], TODAY)
    # archived days are read from files even if the store forgot them
    s2 = Store(":memory:")
    snap(s2, "2026-09-20T10:00", ["Fresh", "Steady"])
    week = archive.period_trends(s2, tmp_path, "KR", 7, TODAY)
    assert week["days_available"] == 5
    top = week["items"][0]
    assert top["label"] == "Steady" and top["days"] == 5 and top["best_rank"] == 1
    assert len(top["series"]) == 5 and top["series"]["2026-09-20"] == 2
    fresh = next(i for i in week["items"] if i["label"] == "Fresh")
    assert fresh["days"] == 1 and fresh["new_in_period"] is True
    # 30-day view over the same data has the same days available
    assert archive.period_trends(s2, tmp_path, "KR", 30, TODAY)["days_available"] == 5


def test_period_segments_counts_days_over_indexed(tmp_path):
    s = Store(":memory:")
    for day, aff in ((18, 180.0), (19, 150.0), (20, 90.0)):
        archive.record_daily_extras(s, date(2026, 9, day), {
            "top_by_segment": {"20대": [{"keyword": "롤", "affinity": aff}, {"keyword": "아이폰", "affinity": 130.0}]},
            "labels": {"롤": "롤(게임)"}}, None)
    p = archive.period_segments(s, tmp_path, 7, TODAY)
    rows = p["by_segment"]["20대"]
    assert p["days_available"] == 3
    assert rows[0] == {"keyword": "아이폰", "days": 3, "avg_affinity": 130.0}
    assert rows[1] == {"keyword": "롤(게임)", "days": 2, "avg_affinity": 165.0}  # day with 90 (< avg) not counted


def test_prune_keeps_ranks_drops_old_payloads():
    s = Store(":memory:")
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    ancient = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    s.save_report({"region": "KR", "generated_at": old, "clusters": [{"key": "a", "label": "A", "score": 1}]})
    s.save_report({"region": "KR", "generated_at": ancient, "clusters": [{"key": "b", "label": "B", "score": 1}]})
    s.prune()
    assert s.snapshot_times("KR") == [old]
    assert s.db.execute("SELECT payload FROM reports").fetchone()[0] == "null"
    assert s.history("a", "KR")  # ranks survive for aggregation


async def test_engine_novelty_uses_past_days():
    from trend_engine.config import Settings
    from trend_engine.engine import TrendEngine

    s = Store(":memory:")
    today = archive.kst_today()
    for back in range(1, 11):  # '문화방송' (a daily wiki regular in the fixtures) was ranked every past day
        d = today - timedelta(days=back)
        snap(s, f"{d.isoformat()}T12:00", ["문화방송"])
    rep = await TrendEngine(Settings(offline=True, db_path=":memory:"), s).collect("KR", save=False)
    regular = next(c for c in rep.clusters if c.label == "문화방송")
    assert regular.days_seen == 10 and regular.novelty == 0.0
    fresh = [c for c in rep.clusters if c.days_seen == 0]
    assert fresh and all(c.novelty == 1.0 for c in fresh)
    assert rep.clusters.index(regular) > len(rep.clusters) // 3  # pushed out of the top third


def test_category_shares_tracks_the_mix_moving(tmp_path):
    s = Store(":memory:")
    day = lambda i: TODAY - timedelta(days=i)
    rows = lambda game, fashion: {"top_by_segment": {"10대":
        [{"keyword": f"g{i}", "affinity": 200, "category": "게임"} for i in range(game)]
        + [{"keyword": f"f{i}", "affinity": 200, "category": "패션·뷰티"} for i in range(fashion)]}, "labels": {}}
    for i, (g, f) in enumerate([(8, 2), (5, 5), (2, 8)]):
        archive.record_daily(s, day(2 - i), "youth", rows(g, f))
    out = archive.category_shares(s, tmp_path, days=7, today=TODAY)
    assert out["days_available"] == 3 and out["dates"][-1] == TODAY.isoformat()
    assert out["by_group"]["10대"]["게임"] == [0.8, 0.5, 0.2]
    assert out["by_group"]["10대"]["패션·뷰티"] == [0.2, 0.5, 0.8]


def test_category_shares_backfills_missing_categories(tmp_path):
    s = Store(":memory:")
    archive.record_daily(s, TODAY - timedelta(days=1), "youth",
                         {"top_by_segment": {"20대": [{"keyword": "a", "category": "게임"}]}})
    archive.record_daily(s, TODAY, "youth",
                         {"top_by_segment": {"20대": [{"keyword": "b", "category": "음악"}]}})
    out = archive.category_shares(s, tmp_path, days=7, today=TODAY)
    assert out["by_group"]["20대"]["게임"] == [1.0, 0.0]
    assert out["by_group"]["20대"]["음악"] == [0.0, 1.0]
