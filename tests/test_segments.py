"""Anchor-normalisation math for Naver DataLab, with a fake poster (no network)."""

import pytest

from trend_engine.config import Settings
from trend_engine.segments import BATCH, Segment, SegmentProfiler, parse_segment

# Fake world: per segment, weekly volume of each keyword (anchor '날씨').
VOLUME = {
    "": {"날씨": 100, "아이돌": 50, "주식": 50, "등산": 20},
    "3,4": {"날씨": 100, "아이돌": 150, "주식": 50, "등산": 5},  # 20대
    "11": {"날씨": 100, "아이돌": 5, "주식": 60, "등산": 80},  # 60대+
}


def make_poster(calls):
    async def poster(body):
        calls.append(body)
        seg = ",".join(body.get("ages", []))
        vol = VOLUME[seg]
        peak = max(vol[g["groupName"]] for g in body["keywordGroups"])  # DataLab normalises per request
        return {"results": [{"title": g["groupName"], "data": [{"period": "d", "ratio": vol[g["groupName"]] / peak * 100}]}
                            for g in body["keywordGroups"]]}
    return poster


async def test_affinity_matches_hand_computation():
    calls = []
    prof = SegmentProfiler(Settings(), poster=make_poster(calls))
    segs = [Segment("20대", ("3", "4")), Segment("60대+", ("11",))]
    r = await prof.profile(["아이돌", "주식", "등산"], segs)

    # overall shares: 50/120, 50/120, 20/120 ; 20대 shares: 150/205, 50/205, 5/205
    assert r.affinity["아이돌"]["20대"] == pytest.approx(150 / 205 / (50 / 120) * 100, abs=0.1)
    assert r.affinity["등산"]["60대+"] > 200
    assert r.top_by_segment["20대"][0]["keyword"] == "아이돌"
    assert r.top_by_segment["60대+"][0]["keyword"] == "등산"
    assert r.relative["아이돌"]["전체"] == 50.0
    assert not r.synthetic and not r.errors
    # every request carries the anchor and at most 5 groups
    assert all(b["keywordGroups"][0]["groupName"] == "날씨" and len(b["keywordGroups"]) <= BATCH + 1 for b in calls)


async def test_batches_more_than_four_keywords():
    calls = []

    async def poster(body):
        calls.append(body)
        return {"results": [{"title": g["groupName"], "data": [{"ratio": 10}]} for g in body["keywordGroups"]]}

    r = await SegmentProfiler(Settings(), poster=poster).profile([f"k{i}" for i in range(9)], [Segment("여성", gender="f")])
    assert len(calls) == 3 * 2  # ceil(9/4) batches x (전체 + 여성)
    assert set(r.keywords) == {f"k{i}" for i in range(9)}


async def test_offline_is_flagged_synthetic():
    r = await SegmentProfiler(Settings(offline=True)).profile(["아이폰", "갤럭시"])
    assert r.synthetic is True


def test_parse_segment():
    assert parse_segment("20대 여성") == Segment("20대 여성", ("3", "4"), "f")
    assert parse_segment("60대+").ages == ("11",)
    assert parse_segment("20대+30대").ages == ("3", "4", "5", "6")
    with pytest.raises(ValueError):
        parse_segment("MZ")


async def test_endpoint_and_headers_follow_naver_api_setting():
    import httpx

    from trend_engine.segments import ENDPOINTS

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = __import__("json").loads(request.content)
        return httpx.Response(200, json={"results": [{"title": g["groupName"], "data": [{"ratio": 50}]} for g in body["keywordGroups"]]})

    for mode in ("hub", "legacy"):
        prof = SegmentProfiler(Settings(naver_client_id="id", naver_client_secret="sec", naver_api=mode))
        prof._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await prof._post({"keywordGroups": [{"groupName": "a", "keywords": ["a"]}]})
        url, id_h, sec_h = ENDPOINTS[mode]
        assert str(seen[-1].url) == url
        assert seen[-1].headers[id_h] == "id" and seen[-1].headers[sec_h] == "sec"
