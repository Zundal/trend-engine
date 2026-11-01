"""Paid app rank: feed quirks, what a blocked upstream does to the run, and the public view."""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from trend_engine import appcharts, publish
from trend_engine.api import create_app
from trend_engine.config import Settings
from trend_engine.sources.base import TransientError


def entry(name, url="https://apps.apple.com/kr/app/x/id1?uo=2"):
    return {"im:name": {"label": name}, "im:artist": {"label": "만든 곳"}, "id": {"label": url},
            "im:price": {"label": "$235.00", "attributes": {"amount": "235.00", "currency": "TWD"}}}


FEED = json.dumps({"feed": {"entry": [entry("가"), entry("나")]}})


def test_parse_ranks_in_feed_order():
    apps = appcharts.parse_chart(FEED)
    assert [(a["rank"], a["name"]) for a in apps] == [(1, "가"), (2, "나")]
    assert apps[0] == {"rank": 1, "name": "가", "artist": "만든 곳", "price": 235.0, "currency": "TWD",
                       "url": "https://apps.apple.com/kr/app/x/id1?uo=2"}


def test_parse_handles_lone_entry_and_empty_chart():
    assert [a["name"] for a in appcharts.parse_chart(json.dumps({"feed": {"entry": entry("하나")}}))] == ["하나"]
    assert appcharts.parse_chart(json.dumps({"feed": {"title": {"label": "비었음"}}})) == []


def test_parse_drops_links_the_page_should_not_open():
    apps = appcharts.parse_chart(json.dumps({"feed": {"entry": [entry("가", "javascript:alert(1)")]}}))
    assert apps[0]["url"] is None


@pytest.fixture
def upstream(monkeypatch):
    """Serves FEED and records URLs; `fail` maps a call number to the exception that call raises."""
    calls, fail = [], {}

    async def fake(client, url, **kw):
        calls.append(url)
        if len(calls) in fail:
            raise fail[len(calls)]
        return FEED

    monkeypatch.setattr(appcharts, "get_text_retry", fake)
    monkeypatch.setattr(appcharts, "PACE_SECONDS", 0)
    return calls, fail


async def test_every_category_is_fetched_then_cached(upstream, store):
    calls, _ = upstream
    d = await appcharts.top(Settings(), store, "JP")
    assert len(calls) == len(appcharts.GENRES) and list(d["categories"]) == list(appcharts.GENRES) and not d["errors"]
    assert calls[0].endswith("/jp/rss/toppaidapplications/limit=20/json")
    assert calls[1].endswith("/jp/rss/toppaidapplications/limit=20/genre=6014/json")
    assert await appcharts.top(Settings(), store, "JP") == d and len(calls) == len(appcharts.GENRES)  # second run: cache


async def test_blocked_upstream_stops_the_run_and_is_retried_next_time(upstream, store):
    calls, fail = upstream
    fail[2] = TransientError("HTTP 429")
    d = await appcharts.top(Settings(), store, "JP")
    assert len(calls) == 2 and list(d["categories"]) == ["전체"] and "429" in d["errors"][0]
    assert store.cache_get("app-charts:v1:JP", timedelta(hours=1)) is None


async def test_one_broken_feed_does_not_hide_the_others(upstream, store):
    calls, fail = upstream
    fail[2] = ValueError("not json")
    d = await appcharts.top(Settings(), store, "JP")
    assert len(calls) == len(appcharts.GENRES) and "게임" not in d["categories"] and "생산성" in d["categories"]
    assert len(d["errors"]) == 1 and store.cache_get("app-charts:v1:JP", timedelta(hours=1)) is None


def test_public_view_drops_errors_and_adult_names_but_keeps_ranks():
    view = publish.public_app_charts({"generated_at": "t", "errors": ["itunes down"], "categories": {"전체": [
        {"rank": 1, "name": "porn hub"}, {"rank": 2, "name": "계산기"}]}})
    assert view == {"generated_at": "t", "categories": {"전체": [{"rank": 2, "name": "계산기"}]}}


def test_api_serves_a_country_and_rejects_unknown_codes(service):
    client = TestClient(create_app(service))
    d = client.get("/api/app-charts?region=JP").json()
    assert d["categories"]["게임"][0]["rank"] == 1 and d["generated_at"]
    assert client.get("/api/app-charts?region=KR-11").json()["categories"]["전체"]  # a city reads its country's chart
    assert client.get("/api/app-charts?region=DE").json()["categories"] == {}  # no sample offline: empty, not an error
    assert client.get("/api/app-charts?region=../x").status_code == 400
