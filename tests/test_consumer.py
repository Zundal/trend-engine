"""소비 트렌드: every parser replays a recorded fixture, lists group into field cards, failures fall back
to the last good result without being cached, and the public view names no shop."""

import json
from datetime import timedelta

import pytest

from trend_engine import consumer, publish
from trend_engine.config import EXPORT_REGIONS, Settings
from trend_engine.consumer import BOARDS, FIELDS, PARSERS, Board
from trend_engine.sources.base import SourceError, TransientError
from trend_engine.store import Store

FIXTURES = Settings(offline=True).fixtures_dir / "consumer"


def test_boards_are_well_formed():
    ids = [b.id for b in BOARDS]
    assert len(ids) == len(set(ids)), "board ids are cache keys and fixture names: they must be unique"
    for b in BOARDS:
        assert b.field in FIELDS, b.id
        assert b.parser in PARSERS, b.id
        assert b.url.startswith("https://"), b.id
        assert b.card and b.tab and b.basis, b.id
    assert {b.country for b in BOARDS} >= set(EXPORT_REGIONS), "every exported country has consumer lists"


def test_every_parser_has_a_fixture():
    used = {b.parser for b in BOARDS}
    recorded = {b.parser for b in BOARDS if consumer.fixture_path(Settings(offline=True), b).exists()}
    assert used == recorded, f"no fixture for parser(s): {sorted(used - recorded)} — run consumer.record"


@pytest.mark.parametrize("board", [b for b in BOARDS if consumer.fixture_path(Settings(offline=True), b).exists()],
                         ids=lambda b: b.id)
def test_fixture_parses_to_a_ranked_list(board):
    raw = consumer.fixture_path(Settings(offline=True), board).read_text(encoding="utf-8")
    items = PARSERS[board.parser](raw)
    assert len(items) >= 5, f"{board.id}: only {len(items)} items"
    assert len(items) <= consumer.LIMIT
    for it in items:
        assert set(it) == {"rank", "name", "by", "price", "note", "url"}
        assert it["name"] and it["name"] == it["name"].strip() and "<" not in it["name"]
        assert isinstance(it["rank"], int) and it["rank"] >= 1
        assert it["url"] is None or it["url"].startswith("https://")
    ranks = [it["rank"] for it in items]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks), f"{board.id}: ranks {ranks}"
    assert PARSERS[board.parser](raw) == items, "parse must be pure (same input, same output)"


def test_itunes_price_is_local_and_free_has_none():
    raw = (FIXTURES / "kr-app-grossing-all.json").read_text(encoding="utf-8")
    items = consumer.parse_itunes(raw)
    assert items[0]["rank"] == 1 and items[0]["url"].startswith("https://apps.apple.com/kr/")
    assert all("?uo=" not in (it["url"] or "") for it in items)
    gb = consumer.parse_itunes((FIXTURES / "gb-toppaidebooks.json").read_text(encoding="utf-8"))
    assert all(it["price"] is None or it["price"].startswith("£") for it in gb)


def test_helpers():
    assert consumer.money("1,234.5", "$", 2) == "$1,234.50"
    assert consumer.money(0, "₩") is None and consumer.money("", "₩") is None and consumer.money(None, "₩") is None
    assert consumer.clean(" <b>A&amp;B</b>\n  C ") == "A&B C"
    rows = [consumer.item(1, "A"), consumer.item(2, "A"), consumer.item(3, ""), consumer.item(4, "B", url="http://x")]
    out = consumer.ranked(rows)
    assert [r["rank"] for r in out] == [1, 4] and out[1]["url"] is None  # duplicate + nameless dropped, ranks kept


async def test_offline_collect_groups_cards_in_field_order(settings, store):
    d = await consumer.collect(settings, store, "US")
    assert d["country"] == "US" and d["errors"] == []
    fields = [c["field"] for c in d["cards"]]
    assert fields == sorted(fields, key=FIELDS.index)
    assert all(c["lists"] and c["lists"][0]["items"] for c in d["cards"])


def _boards(n: int = 3, host: str = "a.example") -> list[Board]:
    return [Board(id=f"t-{host}-{i}", country="ZZ", field="패션", card="카드", tab=f"탭{i}", basis="판매량",
                  url=f"https://{host}/list{i}", parser="fake") for i in range(n)]


@pytest.fixture
def fake(monkeypatch):
    """Fake upstream: url -> body or exception. No network."""
    responses: dict[str, object] = {}
    calls: list[str] = []

    async def fetch(client, b):
        calls.append(b.url)
        r = responses[b.url]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(consumer, "_fetch", fetch)
    monkeypatch.setattr(consumer, "PACE_SECONDS", 0)
    monkeypatch.setitem(consumer.PARSERS, "fake", lambda raw: [consumer.item(i + 1, n) for i, n in enumerate(json.loads(raw))])
    boards: list[Board] = []
    monkeypatch.setattr(consumer, "boards_for", lambda country: boards)
    return responses, calls, boards


async def test_failed_list_falls_back_to_last_good_and_is_not_cached(fake):
    responses, calls, boards = fake
    boards += _boards(2)
    st = Store(":memory:")
    live = Settings(offline=False, db_path=":memory:")
    responses.update({b.url: json.dumps(["x", "y"]) for b in boards})
    first = await consumer.collect(live, st, "ZZ")
    assert [li["stale"] for li in first["cards"][0]["lists"]] == [False, False]

    # cached: no new request inside the ttl
    calls.clear()
    await consumer.collect(live, st, "ZZ")
    assert calls == []

    # past the ttl, list 0 breaks (format) and list 1 works: 0 shows its last good result as stale
    for b in boards:
        st.db.execute("UPDATE cache SET created_at=? WHERE key=?",
                      ((consumer.utcnow() - timedelta(hours=7)).isoformat(), consumer._key(b)))
    responses[boards[0].url] = SourceError("HTTP 404")
    responses[boards[1].url] = json.dumps(["z"])
    again = await consumer.collect(live, st, "ZZ")
    lists = again["cards"][0]["lists"]
    assert lists[0]["stale"] is True and lists[0]["items"][0]["name"] == "x"
    assert lists[1]["stale"] is False and lists[1]["items"][0]["name"] == "z"
    assert len(again["errors"]) == 1 and "404" in again["errors"][0]
    assert st.cache_get(consumer._key(boards[0]), timedelta(hours=6)) is None, "a failure must not refresh the cache"


async def test_blocked_site_stops_but_other_sites_continue(fake):
    responses, calls, boards = fake
    boards += _boards(3, "blocked.example") + _boards(1, "ok.example")
    responses.update({b.url: json.dumps(["x"]) for b in boards})
    responses[boards[0].url] = TransientError("HTTP 429")
    d = await consumer.collect(Settings(offline=False, db_path=":memory:"), Store(":memory:"), "ZZ")
    assert boards[1].url not in calls and boards[2].url not in calls, "the blocked site's other lists wait for next run"
    assert boards[3].url in calls
    assert [li["tab"] for c in d["cards"] for li in c["lists"]] == ["탭0"]  # only ok.example's list
    assert sum("skipped" in e for e in d["errors"]) == 2


async def test_empty_parse_is_an_error_not_an_empty_card(fake):
    responses, calls, boards = fake
    boards += _boards(1)
    responses[boards[0].url] = json.dumps([])
    d = await consumer.collect(Settings(offline=False, db_path=":memory:"), Store(":memory:"), "ZZ")
    assert d["cards"] == [] and "parsed 0 items" in d["errors"][0]


def test_public_view_names_no_shop_and_drops_adult_titles():
    d = {"generated_at": "2026-11-18T00:00:00+00:00", "country": "JP", "errors": ["jp-shop-x: HTTP 503"],
         "cards": [{"id": "jp-shop-x", "field": "패션", "title": "쇼핑몰 베스트", "basis": "판매량", "period": "일간",
                    "lists": [{"tab": "전체", "at": "2026-11-18T00:00:00+00:00", "stale": False,
                               "items": [consumer.item(1, "ポルノ DVD"), consumer.item(2, "コート", by="Brand", price="¥9,900")]},
                              {"tab": "성인", "at": None, "stale": False, "items": [consumer.item(1, "porn")]}]}]}
    p = publish.public_consumer(d)
    plain = json.dumps(p, ensure_ascii=False)
    assert "errors" not in p and "jp-shop-x" not in plain and '"id"' not in plain
    assert p["fields"] == ["패션"]
    assert [li["tab"] for li in p["cards"][0]["lists"]] == ["전체"]  # a list left empty by the filter drops out
    assert [it["rank"] for it in p["cards"][0]["lists"][0]["items"]] == [2]  # ranks stay
    assert '"price"' not in plain  # the tab reads movement, not prices


async def test_service_rejects_unknown_region(service):
    with pytest.raises(ValueError):
        await service.consumer("ZZ")
    assert (await service.consumer("KR"))["country"] == "KR"


@pytest.mark.parametrize("board", [b for b in BOARDS if b.parser in consumer.TRIMS
                                   and consumer.fixture_path(Settings(offline=True), b).exists()], ids=lambda b: b.id)
def test_fixture_trim_keeps_the_parse(board):
    """record() shrinks fixtures before saving: the trim must never change what the parser reads."""
    raw = consumer.fixture_path(Settings(offline=True), board).read_text(encoding="utf-8")
    assert PARSERS[board.parser](consumer.TRIMS[board.parser](raw)) == PARSERS[board.parser](raw)


def test_box_office_reads_both_tables():
    booking = PARSERS["kobis"]((FIXTURES / "kr-boxoffice-booking.html").read_text(encoding="utf-8"))
    daily = PARSERS["kobis"]((FIXTURES / "kr-boxoffice-daily.html").read_text(encoding="utf-8"))
    assert all(it["note"].startswith("예매율 ") for it in booking)
    assert 5 <= len(daily) <= 10 and all("관객" in it["note"] for it in daily)  # the day's top 10 table only
    assert not any(it["name"].isdigit() for it in booking + daily)


def test_game_store_dates_and_prices_read_in_korean():
    from trend_engine.consumer import common

    assert common._released("3 Jul, 2025") == "2025.07 출시" and common._released("Jul 3, 2025") == "2025.07 출시"
    assert common._released("Coming soon") == "출시 예정" and common._released("") is None
    assert common._price(112800, "KRW") == "112,800원" and common._price(59.99, "USD") == "$59.99"
    assert common._price(125000, "VND") == "125,000₫" and common._price(0, "JPY") is None


async def test_json_post_body_and_bot_wall():
    import httpx

    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["ctype"], seen["body"] = req.headers.get("content-type"), req.content
        return httpx.Response(200, text='{"products": []}')

    b = Board(id="t", country="KR", field="패션", card="c", tab="t", basis="b", url="https://x.example/s", parser="gift",
              method="POST", body='{"navId": 2}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        assert await consumer.fetch_raw(c, b) == '{"products": []}'
    assert seen == {"ctype": "application/json", "body": b'{"navId": 2}'}

    wall = httpx.MockTransport(lambda req: httpx.Response(200, text="<title>Just a moment...</title>"))
    async with httpx.AsyncClient(transport=wall) as c:
        with pytest.raises(TransientError):  # a challenge page is a block (rest the site), not a format change
            await consumer.fetch_raw(c, Board(id="t", country="KR", field="패션", card="c", tab="t", basis="b",
                                              url="https://x.example/s", parser="gift"))


def test_korea_lists_split_by_age_and_gender():
    # the purchase ranking ignores the age filter upstream: age/gender tabs live on the click ranking + keywords
    kr = [b for b in BOARDS if b.country == "KR"]
    assert not any(b.age or b.gender for b in kr if b.card == "쇼핑 많이 산 상품")
    views = {b.tab: b for b in kr if b.card == "쇼핑 많이 본 상품"}
    assert {"전체", "10대 여성", "10대 남성", "20대 여성", "20대 남성"} <= set(views)
    assert (views["20대 여성"].age, views["20대 여성"].gender) == (20, "여성") and "PRODUCT_CLICK" in views["전체"].url
    kws = {b.tab: b for b in kr if b.card == "쇼핑 인기 키워드"}
    assert kws["여성"].gender == "여성" and kws["여성"].age == 0 and kws["전체"].kind == "keyword"
    assert any(b.tab == "19세 이하" for b in BOARDS if b.country == "KR" and b.field == "패션")
    assert any(b.field == "공연" for b in BOARDS if b.country == "KR")


def test_crawl_delay_is_kept():
    assert all(b.pace >= 10 for b in BOARDS if "kinokuniya" in b.host)
    assert all(b.pace >= 5 for b in BOARDS if "oricon" in b.host)
