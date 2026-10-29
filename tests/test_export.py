"""Static export: every published file is encrypted, decryptable with the page's key, and source-neutral."""

import json
import re
import struct
from urllib.robotparser import RobotFileParser

import pytest

from trend_engine import publish
from trend_engine.export import export_site
from trend_engine.sources import REGISTRY

KEY_HEX = "11" * 32
# Anything that would reveal where the data came from. Page source: any mention at all.
PROVIDERS = re.compile(r"google_trends|google_news|signal_bz|\bnate\b|wikipedia|youtube\b|datalab|naver|네이버|시그널|네이트|위키|apple_charts|itunes|pixiv|\bptt\b|ettoday|reddit|kenh14|steam|melon|netflix|yahoo_topics|hatena|nicovideo|billboard_japan|livedoor_trend|billboard_us|yahoo_us|official_charts|bbc_news|kkbox_tw|yahoo_tw|yahoo_tw_search|gnn_tw|vnexpress|trends24|getdaytrends|yahoo_trending|yahoo_realtime|zum|tuoitre|dantri|thanhnien|source_status|publisher", re.I)
# Data files: source identifiers as JSON keys/values (headline text may legitimately say "네이버페이").
SOURCE_TOKENS = re.compile(r'"(google_trends|google_news|signal_bz|nate|wikipedia|youtube|apple_charts|pixiv|ptt|ettoday|reddit|kenh14|steam|melon|netflix|yahoo_topics|hatena|nicovideo|billboard_japan|livedoor_trend|billboard_us|yahoo_us|official_charts|bbc_news|kkbox_tw|yahoo_tw|yahoo_tw_search|gnn_tw|vnexpress|trends24|getdaytrends|yahoo_trending|yahoo_realtime|zum_issue|tuoitre|dantri|thanhnien|sources|source_status|publisher|channel|mode|anchor|errors)"')


def google_allows(robots: str, path: str) -> bool:
    """구글 방식: 가장 긴 규칙이 이긴다(길이가 같으면 Allow). urllib.robotparser 는 첫 규칙이 이겨서
    `Allow: /` 뒤의 `Disallow: /api/` 를 못 본다 — 그래서 robotparser 만으로는 구글이 막히는 걸 놓친다.

    shortcut: user-agent 그룹·와일드카드(*, $)는 안 본다 — 지금 robots.txt 엔 없다. 생기면 함께 구현.
    """
    rules = [(0, True)]
    for line in robots.splitlines():
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field in ("allow", "disallow") and value and path.startswith(value):
            rules.append((len(value), field == "allow"))
    return max(rules)[1]


@pytest.fixture(autouse=True)
def fixed_key(monkeypatch):
    monkeypatch.setenv("TREND_ENGINE_DATA_KEY", KEY_HEX)


async def test_export_is_encrypted_and_source_neutral(service, tmp_path):
    lines = await export_site(service, tmp_path / "site", ["KR", "US"], archive_dir=tmp_path / "archive",
                              health_path=tmp_path / "health.json")
    health = json.loads((tmp_path / "health.json").read_text())
    assert set(health) == {"problems", "warnings", "ok", "depth"}
    assert health["depth"] and all(set(d) == {"confirmed", "multi"} for d in health["depth"].values())
    assert any("youtube" in p for p in health["problems"])  # offline US has no video fixture -> reported, not silent
    tmp_path = tmp_path / "site"
    api = tmp_path / "api"
    key = bytes.fromhex(KEY_HEX)
    assert not list(api.glob("*.json")), "no plaintext JSON may be published"

    files = {p.stem: p.read_text() for p in api.glob("*.dat")}
    assert set(files) >= {"meta", "report-KR", "report-US", "history-KR", "history-US", "segments-KR", "shopping",
                          "shopping-month", "period-KR", "period-US", "age-period", "youth", "youth-period", "diffusion", "alerts"}
    assert "segments-US" not in files  # Korean search data isn't published for foreign regions
    for name, blob in files.items():
        # ciphertext is random base64: it can spell 'naver' by chance, so check the *shape* here and
        # scan the decrypted content below
        assert re.fullmatch(r"[A-Za-z0-9+/=]+", blob) and "{" not in blob, f"{name} not encrypted"
        plain = json.dumps(publish.decrypt(blob, key), ensure_ascii=False)
        leak = SOURCE_TOKENS.search(plain)
        assert not leak, f"{name} leaks a source identifier: {leak and leak.group(0)}"

    meta = publish.decrypt(files["meta"], key)
    assert meta["static"] is True and [r["code"] for r in meta["regions"]] == ["KR", "US"]
    assert meta["generated_at"].endswith("+00:00")  # one build time for the page header
    rep = publish.decrypt(files["report-KR"], key)
    assert rep["clusters"] and rep["videos"] and rep["news"] and "sources" not in rep["clusters"][0]
    assert rep["apps"] and all(set(a) == {"title", "url"} for a in rep["apps"])  # app chart only: names, no songs
    assert len(rep["apps"]) <= 20
    assert "local" in rep and all(set(x) <= {"title", "url", "category"} for x in rep["local"])
    hist = publish.decrypt(files["history-KR"], key)
    assert set(hist) == {c["key"] for c in rep["clusters"]}
    assert publish.decrypt(files["shopping"], key)["by_segment"]
    period = publish.decrypt(files["period-KR"], key)
    assert set(period) == {"week", "month"} and period["week"]["days_available"] >= 1 and period["week"]["items"]
    ages = publish.decrypt(files["age-period"], key)
    assert ages["week"]["days_available"] == 1 and ages["week"]["by_segment"]

    page = (tmp_path / "index.html").read_text()
    feed = (tmp_path / "feed.xml").read_text()
    assert feed.startswith("<?xml") and not PROVIDERS.search(feed)  # public RSS: source-free
    assert "let STATIC = true;" in page and f'const DATA_KEY = "{KEY_HEX}";' in page
    assert not PROVIDERS.search(page), PROVIDERS.search(page)
    # the site icon ships as real files: search engines fetch it by URL and want a multiple of 48px
    png = (tmp_path / "favicon-48x48.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (48, 48)
    ico = (tmp_path / "favicon.ico").read_bytes()
    assert ico[:4] == b"\x00\x00\x01\x00" and ico[6:8] == bytes([48, 48])
    assert 'href="favicon-48x48.png"' in page and 'href="favicon.ico"' in page and 'rel="icon" href="data:' not in page
    assert (tmp_path / ".nojekyll").exists()
    site_url = service.settings.site_url.rstrip("/") + "/"
    sitemap = (tmp_path / "sitemap.xml").read_text()
    assert 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' in sitemap
    # 사이트 전체 noindex: 사이트맵은 주소만 두고 URL 은 싣지 않는다
    assert re.findall(r"<loc>(.*?)</loc>", sitemap) == []
    assert page.count('name="robots"') == 1 and '<meta name="robots" content="noindex, follow">' in page
    robots = (tmp_path / "robots.txt").read_text()
    assert f"Sitemap: {site_url}sitemap.xml" in robots
    # 구글은 렌더링 때도 robots 를 지킨다: 홈이 그리는 데이터(api/*.dat)를 막으면 빈 화면만 색인된다
    rp = RobotFileParser()
    rp.parse(robots.splitlines())
    for path in ["/"] + [f"/api/{p.name}" for p in api.iterdir()]:
        assert rp.can_fetch("Googlebot", site_url + path[1:]) and google_allows(robots, path), f"robots.txt blocks {path}"
    assert any(t.get("peers") for t in rep.get("themes") or rep["clusters"]), "비슷한 관심도 peers 가 공개 리포트에 있어야 함"
    assert any("report KR" in line for line in lines)


def test_encrypt_roundtrip_and_tamper_detection():
    key = bytes.fromhex(KEY_HEX)
    blob = publish.encrypt({"a": "한글"}, key)
    assert publish.decrypt(blob, key) == {"a": "한글"}
    assert publish.encrypt({"a": 1}, key) != publish.encrypt({"a": 1}, key)  # random IV
    import base64
    raw = bytearray(base64.b64decode(blob))
    raw[-1] ^= 1
    with pytest.raises(Exception):
        publish.decrypt(base64.b64encode(bytes(raw)).decode(), key)


def test_data_key_validation(monkeypatch):
    monkeypatch.setenv("TREND_ENGINE_DATA_KEY", "abcd")
    with pytest.raises(ValueError):
        publish.data_key()


def test_every_registered_source_is_covered_by_leak_check():
    for name in REGISTRY:
        assert PROVIDERS.search(name) and SOURCE_TOKENS.search(f'"{name}"'), f"add {name} to the leak patterns"
