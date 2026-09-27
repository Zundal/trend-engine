"""같은 개체의 언어별 이름 잇기 — the join that makes country-to-country comparison possible."""

import json

import pytest

from trend_engine.config import Settings
from trend_engine.entities import Entities, parse_sitelinks

RESPONSE = json.dumps({"entities": {
    "Q1": {"sitelinks": {"kowiki": {"title": "오징어 게임"}, "jawiki": {"title": "イカゲーム"},
                         "enwiki": {"title": "Squid Game"}, "dewiki": {"title": "Squid Game"}}},
    "Q2": {"sitelinks": {"kowiki": {"title": "동네 축제"}}},  # only one of our wikis knows it
    "-1": {"missing": ""},
}}, ensure_ascii=False)


def test_parse_keeps_entities_that_exist_in_two_or_more_of_the_languages_we_asked_for():
    got = parse_sitelinks(RESPONSE, ["ko", "ja", "en"])
    assert set(got) == {"Q1"}  # Q2 has one wiki, -1 is a miss
    assert got["Q1"] == {"ko": "오징어 게임", "ja": "イカゲーム", "en": "Squid Game"}  # dewiki not requested


def test_parse_ignores_a_language_the_entity_has_no_article_in():
    assert parse_sitelinks(RESPONSE, ["ko", "vi"]) == {}  # only kowiki matches -> below the floor


@pytest.mark.asyncio
async def test_offline_alignment_reads_fixtures_and_filters_by_the_titles_asked_for(tmp_path):
    fx = tmp_path / "entities"
    fx.mkdir()
    (fx / "sitelinks.json").write_text(json.dumps({"ko": {
        "Q1": {"ko": "오징어 게임", "ja": "イカゲーム"},
        "Q9": {"ko": "다른 것", "en": "Something else"},
    }}, ensure_ascii=False), encoding="utf-8")

    async with Entities(Settings(offline=True, fixtures_dir=tmp_path)) as e:
        got = await e.align(["오징어 게임"], "ko", ["ko", "ja", "en"])
    assert set(got) == {"Q1"}


# --- 출처 태그: 날짜가 정하지, 언어를 훑는 순서가 정하지 않는다 -----------------------------
from datetime import date, timedelta  # noqa: E402

from trend_engine.entities import fair_order, first_origin  # noqa: E402

D = date(2026, 9, 1)


def test_first_origin_is_the_language_that_listed_the_entity_on_the_earliest_day():
    seen = [(D, "ko", {"Q1", "Q2"}),  # ko is looked at first...
            (D - timedelta(days=30), "en", {"Q1"})]  # ...but en had Q1 a month earlier
    assert first_origin(seen) == {"Q1": "en", "Q2": "ko"}


def test_first_origin_is_ambiguous_when_two_languages_list_it_on_the_same_first_day():
    seen = [(D, "ko", {"Q1"}), (D, "en", {"Q1"}), (D + timedelta(days=5), "ja", {"Q1"})]
    assert first_origin(seen) == {"Q1": None}  # a same-day global event has no origin


def test_fair_order_interleaves_origins_and_drops_ambiguous_entities():
    origin = {"k1": "ko", "k2": "ko", "k3": "ko", "e1": "en", "j1": "ja", "x": None}
    assert fair_order(origin) == ["k1", "e1", "j1", "k2", "k3"]

