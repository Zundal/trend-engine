"""Melon / Netflix parse edge cases (beyond the generic contract)."""

from __future__ import annotations

import json

from trend_engine.sources.melon import Melon
from trend_engine.sources.netflix import Netflix, _latest_week_rows


def test_melon_keeps_artist_and_music_category():
    raw = json.dumps({"songs": [
        {"rank": 1, "song": "테스트곡", "artist": "가수A", "songId": 1},
        {"rank": 2, "song": "  ", "artist": "x", "songId": 2},
    ]})
    items = Melon().parse(raw, "KR")
    assert len(items) == 1
    assert items[0].keyword == "테스트곡"
    assert items[0].category == "음악"
    assert items[0].related == ["가수A"]
    assert items[0].rank == 1


def test_netflix_latest_week_only():
    tsv = (
        "week\tcategory\tweekly_rank\tshow_title\tseason_title\tweekly_hours_viewed\truntime\tweekly_views\tcumulative_weeks_in_top_10\n"
        "2026-01-01\tFilms (English)\t1\tOld\tN/A\t1\t1\t1\t1\n"
        "2026-09-20\tTV (Non-English)\t1\tNew Show\tSeason 1\t2\t1\t100\t1\n"
        "2026-09-20\tFilms (English)\t2\tNew Film\tN/A\t3\t1\t50\t1\n"
    )
    week, rows = _latest_week_rows(tsv)
    assert week == "2026-09-20"
    assert len(rows) == 2

    slim = json.dumps({
        "week": week,
        "shows": [
            {"week": week, "category": "TV (Non-English)", "rank": 1, "title": "New Show",
             "season": "Season 1", "views": 100.0},
            {"week": week, "category": "Films (English)", "rank": 2, "title": "New Film",
             "season": "N/A", "views": 50.0},
        ],
    })
    items = Netflix().parse(slim, "US")
    assert [i.keyword for i in items] == ["New Show", "New Film"]
    assert items[0].category == "연예·방송"
    assert items[0].related == ["Season 1"]
    assert items[1].related == []
