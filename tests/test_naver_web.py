"""Keyless Naver paths: DataLab web form (search trend by age/gender) and Shopping Insight."""

import json

import httpx
import pytest

from trend_engine import segments as seg_mod
from trend_engine.config import Settings
from trend_engine.segments import Segment, SegmentProfiler, parse_web_result
from trend_engine.shopping import ShoppingInsight, distinctive, parse_rank

FIX = Settings().fixtures_dir


def test_parse_recorded_trend_result_page():
    data = parse_web_result((FIX / "datalab_web" / "trendResult.html").read_text(encoding="utf-8"))
    titles = [r["title"] for r in data["results"]]
    assert titles == ["날씨", "등산"]
    assert all(len(r["data"]) == 7 and all("ratio" in d for d in r["data"]) for r in data["results"])
    assert max(d["ratio"] for d in data["results"][0]["data"]) == 100.0


def test_naver_mode_auto_selection():
    assert Settings().naver_mode == "web"
    assert Settings(naver_client_id="i", naver_client_secret="s").naver_mode == "hub"
    assert Settings(naver_client_id="i", naver_client_secret="s", naver_api="legacy").naver_mode == "legacy"
    assert Settings(naver_client_id="i", naver_client_secret="s", naver_api="web").naver_mode == "web"


async def test_web_mode_flow_retries_429_and_primes_once(monkeypatch):
    monkeypatch.setattr(seg_mod, "WEB_PACE_SECONDS", 0)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(seg_mod.asyncio, "sleep", no_sleep)
    calls = {"prime": 0, "hash": 0, "result": 0}
    page = (FIX / "datalab_web" / "trendResult.html").read_text(encoding="utf-8")
    seen_forms = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("trendSearch.naver"):
            calls["prime"] += 1
            return httpx.Response(200, text="<html></html>")
        if req.url.path.endswith("qcHash.naver"):
            calls["hash"] += 1
            if calls["hash"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            seen_forms.append(dict(httpx.QueryParams(req.content.decode())))
            return httpx.Response(200, json={"success": True, "hashKey": "N_x"})
        calls["result"] += 1
        return httpx.Response(200, text=page)

    prof = SegmentProfiler(Settings(naver_api="web"))
    prof._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    body = {"startDate": "2026-09-11", "endDate": "2026-09-17", "timeUnit": "date", "gender": "f", "ages": ["3", "4"],
            "keywordGroups": [{"groupName": "날씨", "keywords": ["날씨"]}, {"groupName": "등산", "keywords": ["등산", "캠핑"]}]}
    data = await prof._post(body)
    await prof._post(body)
    assert [r["title"] for r in data["results"]] == ["날씨", "등산"]
    assert calls["prime"] == 1  # re-priming every call triggered Naver's 429s
    assert calls["hash"] == 3  # 1 x 429 retried, then 2 successes
    f = seen_forms[0]
    assert f["queryGroups"] == "날씨__SZLIG__날씨__OUML__등산__SZLIG__등산,캠핑"
    assert (f["startDate"], f["gender"], f["age"]) == ("20260911", "f", "3,4")


def test_shopping_parse_and_distinctive():
    raw = json.dumps({"returnCode": 0, "ranks": [{"rank": 2, "keyword": "b"}, {"rank": 1, "keyword": "a"}]})
    assert parse_rank(raw) == ["a", "b"]
    with pytest.raises(RuntimeError):
        parse_rank(json.dumps({"returnCode": 99, "message": "bad"}))
    assert distinctive(["원피스", "로엠원피스", "후드집업"], ["원피스", "후드집업", "바람막이"]) == ["로엠원피스"]


async def test_shopping_offline_fixture_is_real_sample():
    d = await ShoppingInsight(Settings(offline=True)).top()
    assert d["offline"] is True and d["by_segment"]["20대 여성"]["패션의류"]["top"]
    for cats in d["by_segment"].values():
        for cat, v in cats.items():
            assert set(v["distinctive"]) <= set(v["top"])
            assert not set(v["distinctive"]) & set(d["overall"][cat])


async def test_segments_result_reports_mode():
    async def poster(body):
        return {"results": [{"title": g["groupName"], "data": [{"ratio": 10}]} for g in body["keywordGroups"]]}

    r = await SegmentProfiler(Settings(), poster=poster).profile(["a"], [Segment("여성", gender="f")])
    assert r.mode == "test"
    r2 = await SegmentProfiler(Settings(offline=True)).profile(["a"])
    assert r2.mode == "offline" and r2.synthetic


def test_naver_modes_fallback_order():
    assert Settings().naver_modes == ["web"]
    keyed = Settings(naver_client_id="i", naver_client_secret="s")
    assert keyed.naver_modes == ["hub", "web"]
    assert Settings(naver_client_id="i", naver_client_secret="s", naver_api="legacy").naver_modes == ["legacy", "hub", "web"]
    assert Settings(naver_client_id="i", naver_client_secret="s", naver_api="web").naver_modes == ["web", "hub"]


async def test_api_failure_falls_back_to_web(monkeypatch):
    monkeypatch.setattr(seg_mod, "WEB_PACE_SECONDS", 0)
    page = (FIX / "datalab_web" / "trendResult.html").read_text(encoding="utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "naverapihub.apigw.ntruss.com":
            return httpx.Response(401, text="invalid key")
        if req.url.path.endswith("qcHash.naver"):
            return httpx.Response(200, json={"success": True, "hashKey": "N_x"})
        return httpx.Response(200, text=page if "trendResult" in req.url.path else "<html></html>")

    prof = SegmentProfiler(Settings(naver_client_id="i", naver_client_secret="bad"))
    prof._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    data = await prof._post({"startDate": "2026-09-11", "endDate": "2026-09-17", "timeUnit": "date",
                             "keywordGroups": [{"groupName": "날씨", "keywords": ["날씨"]}]})
    assert data["results"] and prof.used_modes == {"web": 1}
    assert prof.fallback_errors and prof.fallback_errors[0].startswith("hub: DataLab HTTP 401")
