"""End-to-end through HTTP in offline mode: sources -> engine -> store -> API."""

import json
from urllib.robotparser import RobotFileParser

from fastapi.testclient import TestClient

from trend_engine.api import create_app


def test_end_to_end_offline(service):
    client = TestClient(create_app(service))
    home = client.get("/")
    assert home.status_code == 200 and '<meta name="robots" content="noindex, follow">' in home.text
    assert client.get("/favicon-48x48.png").headers["content-type"] == "image/png"
    assert client.get("/favicon.ico").status_code == 200
    site = service.settings.site_url.rstrip("/") + "/"
    sm = client.get("/sitemap.xml")
    assert sm.status_code == 200 and "application/xml" in sm.headers["content-type"]
    assert "<urlset" in sm.text and "<url>" not in sm.text  # 사이트 전체 noindex: 주소는 두고 비운다
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and f"Sitemap: {site}sitemap.xml" in robots.text
    rp = RobotFileParser()  # serve 의 /api/ 는 호출마다 수집하는 동적 API 라 막는다 (첫 규칙이 이기는 파서에서도)
    rp.parse(robots.text.splitlines())
    assert rp.can_fetch("Googlebot", site) and not rp.can_fetch("Googlebot", f"{site}api/report?refresh=true")

    meta = client.get("/api/meta").json()
    assert meta["offline"] is True and any(r["code"] == "KR" for r in meta["regions"])
    assert set(meta) == {"regions", "offline", "static"}  # no source list exposed

    rep = client.get("/api/report", params={"region": "KR"}).json()
    assert rep["region"] == "KR" and len(rep["clusters"]) >= 10
    assert rep["videos"] and rep["news"]
    assert "source_status" not in rep and "sources" not in rep["clusters"][0]


    seg = client.get("/api/segments", params={"region": "KR", "top": 8}).json()
    assert seg["synthetic"] is True and set(seg["segments"]) >= {"20대", "여성"}
    assert "mode" not in seg and "anchor" not in seg

    kw = client.get("/api/keyword", params={"q": "아이폰,갤럭시", "segments": "20대 여성,50대"}).json()
    assert kw["segments"] == ["20대 여성", "50대"]
    assert client.get("/api/keyword", params={"q": "x", "segments": "MZ"}).status_code == 400

    shop = client.get("/api/shopping").json()
    assert shop["by_segment"] and shop["offline"] is True

    key = rep["clusters"][0]["key"]
    assert len(client.get("/api/history", params={"key": key}).json()) >= 1

    json.dumps(rep, ensure_ascii=False)


def test_unsupported_region_still_works(service):
    """Region with only some fixtures: missing sources degrade, report still renders."""
    rep = TestClient(create_app(service)).get("/api/report", params={"region": "US"}).json()
    assert rep["clusters"]
    assert rep["videos"] == []  # no US video fixture -> empty, not an error
    raw = service.store.latest_report("US")
    assert raw["source_status"]["youtube"]["ok"] is False
    assert "signal_bz" not in raw["source_status"]  # Korea-only source not attempted
