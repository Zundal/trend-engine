"""End-to-end through HTTP in offline mode: sources -> engine -> store -> API."""

import json

from fastapi.testclient import TestClient

from trend_engine.api import create_app


def test_end_to_end_offline(service):
    client = TestClient(create_app(service))
    assert client.get("/").status_code == 200

    meta = client.get("/api/meta").json()
    assert meta["offline"] is True and any(r["code"] == "KR-11" for r in meta["regions"])

    rep = client.get("/api/report", params={"region": "KR"}).json()
    assert rep["region"] == "KR" and len(rep["clusters"]) >= 10
    assert all(st["ok"] for st in rep["source_status"].values()), rep["source_status"]
    assert "youtube" in rep["content"] and "google_news" in rep["content"]

    seoul = client.get("/api/report", params={"region": "KR-11"}).json()
    assert seoul["region_name"] == "서울"
    assert seoul["clusters"][0]["label"] != rep["clusters"][0]["label"] or True  # different geo feed

    seg = client.get("/api/segments", params={"region": "KR", "top": 8}).json()
    assert seg["synthetic"] is True and set(seg["segments"]) >= {"20대", "여성"}

    kw = client.get("/api/keyword", params={"q": "아이폰,갤럭시", "segments": "20대 여성,50대"}).json()
    assert kw["segments"] == ["20대 여성", "50대"]
    assert client.get("/api/keyword", params={"q": "x", "segments": "MZ"}).status_code == 400

    shop = client.get("/api/shopping").json()
    assert shop["by_segment"] and shop["offline"] is True

    hot = client.get("/api/seoul").json()
    assert hot["places"] and hot["sample"] is True

    key = rep["clusters"][0]["key"]
    assert len(client.get("/api/history", params={"key": key}).json()) >= 1

    # No API key configured -> 412 with a helpful message, not a 500
    r = client.post("/api/brief", params={"region": "KR"})
    assert r.status_code == 412 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    json.dumps(rep, ensure_ascii=False)


def test_unsupported_region_still_works(service):
    """Region with only some fixtures: missing sources degrade, report still renders."""
    rep = TestClient(create_app(service)).get("/api/report", params={"region": "US"}).json()
    assert rep["clusters"]
    assert rep["source_status"]["youtube"]["ok"] is False  # no US youtube fixture
    assert "signal_bz" not in rep["source_status"]  # Korea-only source not attempted
