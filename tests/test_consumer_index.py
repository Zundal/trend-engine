"""한국 쇼핑 클릭 지수(consumer/shopindex.py)와 소비 탭의 기록·요약(trends.daily/history/summary) — 네트워크 없음."""

from __future__ import annotations

import asyncio
import json
from datetime import date

from trend_engine import archive, consumer
from trend_engine.config import Settings
from trend_engine.consumer import shopindex as si
from trend_engine.consumer import trends
from trend_engine.store import Store

WEEKS = si.periods(date(2025, 11, 17))
NAMES = [n for n, _ in si.CATS]


def test_window_takes_finished_weeks_only():
    assert si.window(date(2026, 11, 18)) == (date(2025, 10, 13), date(2026, 11, 15))  # Wed → last Sunday, 57 weeks
    assert si.window(date(2026, 11, 17))[1] == date(2026, 11, 15)  # Tue: Sunday's numbers are in
    assert si.window(date(2026, 11, 16))[1] == date(2026, 11, 8)  # Mon: not yet
    assert len(si.periods(si.window(date(2026, 11, 18))[0])) == si.WEEKS


def test_parse_reads_category_ids_and_keywords():
    raw = json.dumps({"result": [{"code": "50000006", "title": "식품", "data": [{"period": "20261102", "value": 7.5}]},
                                 {"code": None, "title": "과메기", "data": []}]})
    assert si.parse(raw) == {"50000006": {"20261102": 7.5}, "과메기": {}}


def test_chain_puts_every_category_on_one_scale():
    w = ["20261102", "20261109"]
    first = {si.CID["패션의류"]: {w[0]: 10.0, w[1]: 20.0}, si.CID["패션잡화"]: {w[0]: 5.0, w[1]: 5.0}}
    second = {si.CID["패션의류"]: {w[0]: 5.0, w[1]: 10.0}, si.CID["식품"]: {w[0]: 2.0}}  # its own max: half the scale
    got = si.chain([first, second], w)
    assert got["패션잡화"] == [5.0, 5.0] and got["식품"] == [4.0, 0.0]  # missing week = 0


def _group(food_from: int = 0, beauty: float = 1.0, shrink: float = 1.0) -> dict[str, list[float]]:
    """57 weeks, every category 1.0 a week; 식품 doubles in the last 4 weeks; the whole portal can shrink."""
    out = {}
    for c in NAMES:
        v = [1.0] * len(WEEKS)
        if c == "식품" and food_from:
            v[-food_from:] = [2.0] * food_from
        if c == "화장품·미용":
            v = [x * beauty for x in v]
        out[c] = [x * (shrink if i >= 5 else 1) for i, x in enumerate(v)]
    return out


def test_build_reads_share_lean_change_and_year():
    idx = si.build({"전체": _group(food_from=4, shrink=0.6), "20대 여성": _group(beauty=3.0)}, WEEKS)
    g0, g = idx["groups"]
    assert len(idx["weeks"]) == si.SHOW and idx["until"] == "2026-12-20"
    assert abs(sum(g0["share"].values()) - 100) < 0.5 and g0["share"]["식품"] == 16.7  # 1.2 of 7.2 a week
    assert g0["change"]["식품"] == 100 and g0["change"]["패션의류"] == 0
    # the portal shrank 40% in a year: by share, only 식품 grew — nothing 'fell by 40%'
    assert g0["yoy"]["식품"] > 0 and all(g0["yoy"][c] <= 0 for c in NAMES if c != "식품")
    assert g["over"]["화장품·미용"] > 2 and g["label"] == "20대 여성" and (g["age"], g["gender"]) == (20, "여성")
    assert g["headline"].startswith("20대 여성은 쇼핑 클릭의") and "화장품·미용을 2.8배 더 봐요" in g["headline"]
    assert g0["moves"].startswith("최근 4주 가장 늘어난 분야는 식품(+100%)")
    assert all(len(s) == si.SHOW for s in g0["series"].values())
    assert si.build({"20대": _group()}, WEEKS) is None  # nothing to compare a group with


def test_build_skips_a_group_missing_a_category():
    half = {c: v for c, v in _group().items() if c != "도서"}
    idx = si.build({"전체": _group(), "10대": half}, WEEKS)
    assert [g["label"] for g in idx["groups"]] == ["전체"]


def test_josa_follows_the_last_syllable():
    assert si.josa("20대 여성", "은/는") == "20대 여성은" and si.josa("60대+", "은/는") == "60대+는"
    assert si.josa("식품", "을/를") == "식품을" and si.josa("도서", "을/를") == "도서를"


def test_keywords_are_asked_where_they_are_sold():
    assert si.cats_for(["뷰티"]) == ["화장품·미용"]
    assert si.cats_for(["패션", "종합 쇼핑"])[:3] == ["패션의류", "패션잡화", "식품"]
    assert si.cats_for(["게임", "영화"]) == []
    every = {w: 3.0 for w in WEEKS}
    stray = {WEEKS[3]: 6.0, WEEKS[9]: 1.0, **{w: 1.0 for w in WEEKS[20:28]}}  # 10 weeks, none lately
    assert si.sold_there(every, WEEKS) and not si.sold_there(stray, WEEKS)
    season = {w: 1.0 for w in WEEKS[-10:]}  # 과메기: only this autumn, every week lately
    assert si.sold_there(season, WEEKS)


def test_keyword_line_is_a_slice_of_its_category():
    base = [10.0 * (0.6 if i >= 20 else 1) for i in range(len(WEEKS))]  # the portal shrinks
    flat = si.spark([b * 0.1 for b in base], base)
    assert set(flat["series"]) == {100} and flat["change"] == 0 and flat["yoy"] == 0  # not 'fading'
    new = si.spark([0.0] * 10 + [0.01] * 30 + [1.0] * 17, [1.0] * len(WEEKS))
    assert new["yoy"] is None and new["fresh"]
    assert si.spark([0.0] * len(WEEKS)) is None
    assert si.spark([1.0] * len(WEEKS))["yoy"] is None  # no category line: no year-on-year either


def test_offline_index_and_keyword_lines_from_fixtures():
    settings, store = Settings(offline=True), Store(":memory:")
    idx, base, errors = asyncio.run(si.collect(settings, store, date(2026, 11, 18)))
    assert not errors and idx["groups"][0]["label"] == "전체" and base
    labels = [g["label"] for g in idx["groups"]]
    assert {"10대", "60대+", "여성", "남성", "20대 여성"} <= set(labels)
    assert date.fromisoformat(idx["until"]).weekday() == 6
    themes = [{"term": "과메기", "fields": ["종합 쇼핑"]}, {"term": "자라", "fields": ["종합 쇼핑"]},
              {"term": "콘서트", "fields": ["공연"]}]
    got, _ = asyncio.run(si.keyword_trends(settings, store, date(2026, 11, 18), themes, base))
    assert set(got) >= {"과메기", "자라"} and "콘서트" not in got
    assert len(got["과메기"]["series"]) == si.SHOW and got["과메기"]["change"] > 50  # 겨울 제철


def test_collect_attaches_index_and_lines_to_korea_only():
    settings, store = Settings(offline=True), Store(":memory:")
    kr = asyncio.run(consumer.collect(settings, store, "KR"))
    us = asyncio.run(consumer.collect(settings, store, "US"))
    assert kr["index"] and any(t.get("spark") for t in kr["themes"]) and kr["record"] is None  # offline: no record
    assert us["index"] is None


def test_daily_record_becomes_a_day_by_day_line():
    themes = [{"term": "패딩", "score": 4.0}, {"term": "과메기", "score": 2.0}]
    rising = [{"field": "패션"}, {"field": "패션"}, {"field": "식품"}]
    rec = trends.daily(themes, rising)
    assert rec["fields"] == {"패션": 2, "식품": 1}
    later = trends.daily([{"term": "패딩", "score": 8.0}], [{"field": "게임"}])
    h = trends.history([("2026-11-16", rec), ("2026-11-17", rec), ("2026-11-18", later)])
    assert h["fields"] == {"패션": [2, 2, 0], "식품": [1, 1, 0], "게임": [0, 0, 1]}  # FIELDS order
    rows = [{"term": "패딩"}, {"term": "과메기"}, {"term": "새말", "spark": {"unit": "week"}}]
    trends.attach_history(rows, h)
    assert rows[0]["spark"]["series"] == [50, 50, 100] and rows[0]["spark"]["unit"] == "day"
    assert rows[1]["spark"]["series"] == [100, 100, 0] and rows[2]["spark"] == {"unit": "week"}
    short = [{"term": "패딩"}]
    trends.attach_history(short, trends.history([("2026-11-18", rec)]))
    assert "spark" not in short[0]  # one day is not a line


def test_daily_record_is_archived_and_read_back(tmp_path):
    store = Store(":memory:")
    rec = {"themes": {"패딩": ["패딩", 4.0]}, "fields": {"패션": 2}}
    archive.record_daily(store, date(2026, 11, 16), "consumer-KR", rec)
    archive.record_daily(store, date(2026, 11, 18), "consumer-KR", rec)  # today: stays in the store
    written = archive.finalize(store, tmp_path, [], today=date(2026, 11, 18))
    assert written == ["2026-11-16/consumer-KR.json"]
    store.cache_delete("daily:consumer-KR:2026-11-16")  # the cache is gone: the archive still has it
    got = archive.consumer_history(store, tmp_path, "KR", days=5, today=date(2026, 11, 18))
    assert [d for d, _ in got] == ["2026-11-16", "2026-11-18"] and got[0][1] == rec


def test_summary_tiles_lead_with_the_click_index_in_korea():
    idx = si.build({"전체": _group(food_from=4), "20대 여성": _group(beauty=3.0)}, WEEKS)
    view = {"index": idx, "rising": [{"field": "패션"}], "themes": [{"term": "패딩"}, {"term": "과메기"}],
            "world": {"shared": [{"name": "Minecraft", "countries": {"KR": {}, "US": {}, "JP": {}}, "field": "게임"}]}}
    tiles = trends.summary(view)
    assert [t["label"] for t in tiles] == ["가장 늘어난 쇼핑 분야", "유독 많이 보는 분야", "뜨는 소비 키워드", "여러 나라에서 동시에"]
    assert tiles[0]["value"] == "식품" and tiles[0]["delta"] == 100
    assert tiles[1]["value"] == "20대 여성 · 화장품·미용" and tiles[3]["sub"] == "3개국 순위 · 게임"
    early = si.build({"전체": _group(), "20대": _group(beauty=2.0)}, WEEKS)  # this week's 나이×성별 not in yet
    assert trends.summary({"index": early})[0]["value"] == "20대 · 화장품·미용"
    other = trends.summary({"rising": [{"field": "게임"}, {"field": "게임"}, {"field": "영화"}], "themes": []})
    assert [t["value"] for t in other] == ["3개", "게임"] and other[1]["sub"] == "뜨는 것의 67% (2개)"
