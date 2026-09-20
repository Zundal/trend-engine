"""Static export: every published file is encrypted, decryptable with the page's key, and source-neutral."""

import json
import re

import pytest

from trend_engine import publish
from trend_engine.export import export_site
from trend_engine.sources import REGISTRY

KEY_HEX = "11" * 32
# Anything that would reveal where the data came from. Page source: any mention at all.
PROVIDERS = re.compile(r"google_trends|google_news|signal_bz|\bnate\b|wikipedia|youtube\b|datalab|naver|네이버|시그널|네이트|위키|apple_charts|itunes|source_status|publisher", re.I)
# Data files: source identifiers as JSON keys/values (headline text may legitimately say "네이버페이").
SOURCE_TOKENS = re.compile(r'"(google_trends|google_news|signal_bz|nate|wikipedia|youtube|apple_charts|sources|source_status|publisher|channel|mode|anchor|errors)"')


@pytest.fixture(autouse=True)
def fixed_key(monkeypatch):
    monkeypatch.setenv("TREND_ENGINE_DATA_KEY", KEY_HEX)


async def test_export_is_encrypted_and_source_neutral(service, tmp_path):
    lines = await export_site(service, tmp_path / "site", ["KR", "US"], archive_dir=tmp_path / "archive",
                              health_path=tmp_path / "health.json")
    health = json.loads((tmp_path / "health.json").read_text())
    assert set(health) == {"problems", "warnings", "ok"}
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
    rep = publish.decrypt(files["report-KR"], key)
    assert rep["clusters"] and rep["videos"] and rep["news"] and "sources" not in rep["clusters"][0]
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
    assert (tmp_path / ".nojekyll").exists()
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
