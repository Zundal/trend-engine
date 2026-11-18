"""소비 트렌드 읽기(consumer/trends.py): 합성 순위표로 뜨는 것·키워드·세대 차이·나라 비교를 검사한다."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from trend_engine import consumer, publish
from trend_engine.config import Settings
from trend_engine.consumer import Board, item, trends
from trend_engine.store import Store


def board(id: str, card: str = "베스트", tab: str = "전체", field: str = "패션", period: str = "일간", **kw) -> Board:
    return Board(id=id, country=kw.pop("country", "KR"), field=field, card=card, tab=tab, basis="", url="https://x",
                 parser="snx", period=period, **kw)


def ranked(*names: str, notes: dict[int, str] | None = None, urls: dict[int, str] | None = None) -> dict:
    notes, urls = notes or {}, urls or {}
    return {"at": None, "items": [item(i, n, note=notes.get(i), url=urls.get(i)) for i, n in enumerate(names, 1)]}


FILLER = [f"상품{i}" for i in range(1, 21)]


def test_upstream_moves_read_in_one_vocabulary():
    mv = lambda note, rank=5: trends.upstream_move(item(rank, "x", note=note))  # noqa: E731
    assert mv("새로 진입") == ("new", 0) and mv("새 개봉") == ("new", 0)
    assert mv("12계단 상승") == ("up", 12) and mv("지난 9위", 5) == ("up", 4)
    assert mv("지난 3위", 5) is None and mv("3계단 하락") is None and mv("리뷰 1,234") is None
    assert mv("급상승") == ("up", 0)


def test_rising_mixes_upstream_moves_and_yesterday_snapshot():
    daily, weekly, hot = board("d"), board("w", card="주간", period="주간"), board("h", card="화장품 랭킹 · 급상승", field="뷰티")
    today = ranked("롱패딩", *FILLER[:19])
    yesterday = [[trends.ikey(item(1, n)), r] for r, n in enumerate(FILLER[:19] + ["바람막이"], 1)]
    lists = {"d": today, "w": ranked("코트", "니트", notes={2: "15계단 상승"}), "h": ranked("수분크림"),
             "stale": ranked("오래된") | {"stale": True}}
    rows = trends.rising([daily, weekly, hot, board("stale")], lists, {"d": yesterday, "w": [[trends.ikey(item(1, "x")), 1]] * 12})
    by = {r["name"]: r for r in rows}
    assert by["롱패딩"]["signal"] == "새로 진입 · 1위" and by["롱패딩"]["move"] == "new"  # not in yesterday's list
    assert "상품1" not in by  # moved 2→1 only: below the 3-step bar
    assert by["니트"]["signal"] == "15계단 상승 · 2위"
    assert "코트" not in by  # weekly lists are not compared with yesterday
    assert by["수분크림"]["signal"] == "급상승 1위"
    assert "오래된" not in by  # a stale list says nothing about today
    assert rows[0]["name"] == "롱패딩"


def test_rising_counts_an_item_once_across_lists():
    a, b = board("a", tab="여성"), board("b", tab="남성")
    lists = {"a": ranked("경량패딩", notes={1: "새로 진입"}), "b": ranked("x", "경량패딩", notes={2: "3계단 상승"})}
    rows = trends.rising([a, b], lists)
    assert [r["name"] for r in rows] == ["경량패딩"] and rows[0]["lists"] == 2 and rows[0]["where"] == "베스트 · 여성"


def test_themes_need_several_lists_skip_list_names_and_fold_synonyms():
    bs = [board("a", tab="아우터"), board("b", tab="여성"), board("c", field="종합 쇼핑", tab="전체"),
          board("kw", card="쇼핑 인기 키워드", field="종합 쇼핑", kind="keyword")]
    lists = {
        "a": ranked("숏 패딩 아우터", "롱 패딩 아우터", "경량 패딩 조끼 아우터"),
        "b": ranked("오버핏 패딩 점퍼", "니트 가디건", "일본 eSIM 5일"),
        "c": ranked("일본 eSIM 도쿄 무제한", "일본 eSIM 오사카", "무료배송 니트"),
        "kw": ranked("과메기", notes={1: "새로 진입"}),
    }
    got = {t["term"]: t for t in trends.themes(bs, lists)}
    assert got["패딩"]["items"] == 4 and got["패딩"]["lists"] == 2
    assert "아우터" not in got  # the list is called 아우터: every item saying so is no news
    assert "무료배송" not in got  # promo words never make a theme
    assert got["과메기"]["keyword"] and got["과메기"]["examples"] == []
    esim = next(t for t in got.values() if {t["term"], *t["also"]} >= {"일본", "esim"})  # one theme, not three
    assert esim["items"] == 3
    assert "니트" not in got  # two items only


def test_theme_trend_against_a_week_ago():
    before = {f"w{i}": 1.0 for i in range(10)} | {"패딩": 1.0, "니트": 5.0}
    assert trends._trend("패딩", 2.0, before) == {"move": "up", "pct": 100}
    assert trends._trend("니트", 2.0, before)["move"] == "down"
    assert trends._trend("과메기", 2.0, before) == {"move": "new"}
    assert trends._trend("패딩", 2.0, {"패딩": 1.0}) is None  # too little history to say


def test_cjk_words_whole_katakana_and_han_pieces():
    assert trends.grams("ドラゴンクエストVII Reimagined") == {"ドラゴンクエスト"}  # never 'イン'
    assert {"炊飯器", "象印"} <= trends.grams("象印 圧力IH炊飯器 ブラック")
    assert "ブラック" not in trends.grams("象印 圧力IH炊飯器 ブラック")
    assert trends.words("[무료배송] 남성 기모 바지 2개 SET") == {"기모", "바지"}


def test_segments_compare_young_tabs_with_older_ones():
    card = dict(card="패션 연령대별", field="패션")
    bs = [board("y", tab="20대", age=20, **card), board("o1", tab="30대", age=30, **card),
          board("o2", tab="40대", age=40, **card), board("all", tab="전체", **card)]
    lists = {"y": ranked("커브드 데님", "커브드 와이드 팬츠", "커브드 벌룬 팬츠", "기본 코트"),
             "o1": ranked("기본 코트", "캐시미어 니트"), "o2": ranked("캐시미어 머플러", "기본 코트"),
             "all": ranked("기본 코트")}
    (g,) = trends.segments(bs, lists)
    assert g["label"] == "20대" and g["vs"] == "30대 이상" and g["list"] == "패션 연령대별"
    assert [it["name"] for it in g["only"]] == ["커브드 데님", "커브드 와이드 팬츠", "커브드 벌룬 팬츠"]
    assert g["terms"][0] == {"term": "커브드", "items": 3, "older": "없음"}


def test_segments_by_gender_and_within_gender():
    card = dict(card="쇼핑 인기 키워드", field="종합 쇼핑", kind="keyword")
    bs = [board("w", tab="여성", gender="여성", **card), board("m", tab="남성", gender="남성", **card),
          board("w20", tab="20대 여성", age=20, gender="여성", **card), board("w40", tab="40대 여성", age=40, gender="여성", **card),
          board("m40", tab="40대 남성", age=40, gender="남성", **card)]
    lists = {"w": ranked("자라", "호떡"), "m": ranked("자라", "폴드8"), "w20": ranked("볶음너구리", "자라"),
             "w40": ranked("자라", "김장"), "m40": ranked("볶음너구리")}
    got = {g["label"]: g for g in trends.segments(bs, lists)}
    assert got["20대 여성"]["vs"] == "30대 이상 여성"  # men's tabs are not the reference
    assert [it["name"] for it in got["20대 여성"]["only"]] == ["볶음너구리"]
    assert [it["name"] for it in got["여성"]["only"]] == ["호떡"] and got["여성"]["vs"] == "남성"
    assert got["여성"]["terms"] == []  # a keyword list is its own words


def _country(code: str, apps: list[tuple[str, str]], extra_tab: list[str] | None = None) -> dict:
    lists = [{"tab": "전체", "items": [item(i, n, url=f"https://apps.apple.com/{code.lower()}/app/x/id{aid}")
                                     for i, (n, aid) in enumerate(apps, 1)]}]
    cards = [{"field": "앱 결제", "title": "앱 매출 순위", "lists": lists}]
    if extra_tab:
        cards.append({"field": "도서", "title": "서점", "lists": [{"tab": "소설", "items": [item(1, extra_tab[0])]}]})
    return {"cards": cards, "rising": []}


def test_world_links_by_store_id_and_finds_what_only_one_country_has():
    by = {"KR": _country("KR", [("카카오톡", "1"), ("유튜브", "2"), ("메이플", "3")], ["소년이 온다"]),
          "US": _country("US", [("YouTube", "2"), ("Tinder", "4"), ("ChatGPT", "5")]),
          "JP": _country("JP", [("ChatGPT", "5"), ("YouTube", "2"), ("LINE", "6")]),
          "TW": _country("TW", [("ChatGPT", "5"), ("YouTube", "2")])}
    by["KR"]["rising"] = [{"key": "ios:2"}]
    w = trends.world(by)
    first = w["shared"][0]
    assert first["key"] == "ios:2" and set(first["countries"]) == {"KR", "US", "JP", "TW"}  # names differ, id doesn't
    assert first["countries"]["KR"]["rank"] == 2 and first["rising_in"] == ["KR"]
    assert w["shared"][1]["key"] == "ios:5" and "KR" not in w["shared"][1]["countries"]
    assert [r["name"] for r in w["local"]["KR"]] == ["카카오톡", "메이플"]  # the bookshop list exists only in KR
    assert "Tinder" in [r["name"] for r in w["local"]["US"]]


def test_snapshot_round_trip_makes_yesterday_the_baseline():
    """Offline collect never writes snapshots, but it reads one: a list item absent yesterday shows as new."""
    settings, store = Settings(offline=True), Store(":memory:")
    today = asyncio.run(consumer.collect(settings, store, "KR"))
    assert today["compare"] == {"rising": None, "themes": None}
    lists = consumer._offline(settings, consumer.boards_for("KR"))
    snap = trends.snapshot(lists, today["themes"])
    snap["lists"]["kr-shopview-all"] = snap["lists"]["kr-shopview-all"][1:] + [["gone", 20]]  # drop today's #1
    yday = consumer._kst_day() - timedelta(days=1)
    store.cache_set(consumer._snap_key("KR", yday), snap)
    store.cache_set(consumer._snap_key("KR", yday - timedelta(days=6)), snap)
    again = asyncio.run(consumer.collect(settings, store, "KR"))
    assert again["compare"] == {"rising": 1, "themes": 7}
    first = lists["kr-shopview-all"]["items"][0]["name"]
    assert any(r["name"] == first and r["signal"].startswith("새로 진입") for r in again["rising"])
    assert all(t["trend"] is not None for t in again["themes"])


def test_public_view_keeps_trends_without_keys_or_prices():
    store = Store(":memory:")
    from trend_engine.service import TrendService

    svc = TrendService(Settings(offline=True, db_path=":memory:"), store)
    p = publish.public_consumer(asyncio.run(svc.consumer("KR")))
    assert p["rising"] and p["themes"] and p["segments"] and p["world"]["shared"]
    assert set(p["world"]["countries"]) >= {"KR", "US", "JP"}
    plain = str(p)
    assert "'key'" not in plain and "'price'" not in plain and "'score'" not in str(p["rising"])
    assert all(r["countries"]["KR"] for r in p["world"]["shared"] if "KR" in r["countries"])


def test_keyword_themes_say_who_searches_them():
    card = dict(card="쇼핑 인기 키워드", field="종합 쇼핑", kind="keyword")
    bs = [board("a", tab="전체", **card), board("w20", tab="20대 여성", age=20, gender="여성", **card),
          board("m40", tab="40대 남성", age=40, gender="남성", **card)]
    lists = {"a": ranked("x", "볶음너구리"), "w20": ranked("볶음너구리"), "m40": ranked("y", "z", "볶음너구리")}
    t = next(t for t in trends.themes(bs, lists) if t["term"] == "볶음너구리")
    assert t["who"] == [{"tab": "20대 여성", "rank": 1}, {"tab": "40대 남성", "rank": 3}] and t["items"] == 0
