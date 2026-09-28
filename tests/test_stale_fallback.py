"""IP-level upstream blocks outlast any in-run retry — reuse the last good result for a while.

news.google.com answers some GitHub-hosted runner IPs with a 503 "Sorry..." page for the whole
run (every region, ~7 minutes), then the next hourly run on a fresh IP is fine. Without a fallback
each such run drops the news source and opens the warning issue for nothing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from trend_engine.config import Settings, get_region
from trend_engine.engine import TrendEngine
from trend_engine.health import Health
from trend_engine.models import TrendItem
from trend_engine.sources.base import SourceError, TransientError
from trend_engine.sources.google_news import GoogleNews
from trend_engine.store import Store


class _Scripted(GoogleNews):
    """google_news whose collect() plays back canned outcomes (item list or exception)."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)

    async def collect(self, client, region, settings):
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _items(region="KR"):
    return [TrendItem(source="google_news", region=region, rank=i, keyword=f"헤드라인 {i}", kind="content")
            for i in (1, 2)]


BLOCKED = TransientError("HTTP 503 from https://news.google.com/rss: <title>Sorry...</title>")


@pytest.fixture
def engine():
    return TrendEngine(Settings(offline=False, db_path=":memory:"), Store(":memory:"))


def _status(engine, results):
    _, status, content = engine._build(results, get_region("KR"), save=False)
    return status, content


@pytest.mark.asyncio
async def test_block_reuses_last_good_result(engine):
    src = _Scripted(_items(), BLOCKED)
    kr = get_region("KR")
    assert (await engine._run_source(src, None, kr))[2] is None  # fresh; remembered

    name, items, stale = await engine._run_source(src, None, kr)
    assert name == "google_news" and [i.keyword for i in items] == ["헤드라인 1", "헤드라인 2"]
    assert "HTTP 503" in stale

    status, content = _status(engine, [(name, items, stale)])
    assert status["google_news"]["ok"] and status["google_news"]["stale"] == stale
    assert len(content["google_news"]) == 2


@pytest.mark.asyncio
async def test_block_longer_than_stale_ok_is_a_real_failure(engine, monkeypatch):
    src = _Scripted(_items(), BLOCKED)
    kr = get_region("KR")
    await engine._run_source(src, None, kr)
    monkeypatch.setattr(GoogleNews, "stale_ok", timedelta(0))  # remembered result is now too old

    name, res, stale = await engine._run_source(src, None, kr)
    assert res is BLOCKED and stale is None
    assert not _status(engine, [(name, res, stale)])[0]["google_news"]["ok"]


@pytest.mark.asyncio
async def test_non_transient_errors_never_use_the_fallback(engine):
    """A format change must alert immediately, not hide behind yesterday's feed."""
    broken = SourceError("HTTP 404 from https://news.google.com/rss")
    parse_err = ValueError("not well-formed")
    src = _Scripted(_items(), broken, parse_err)
    kr = get_region("KR")
    await engine._run_source(src, None, kr)
    assert (await engine._run_source(src, None, kr))[1] is broken
    assert (await engine._run_source(src, None, kr))[1] is parse_err


@pytest.mark.asyncio
async def test_last_good_is_per_region(engine):
    src = _Scripted(_items("KR"), BLOCKED)
    await engine._run_source(src, None, get_region("KR"))
    assert (await engine._run_source(src, None, get_region("US")))[1] is BLOCKED


@pytest.mark.asyncio
async def test_offline_mode_does_not_remember(tmp_path):
    engine = TrendEngine(Settings(offline=True, db_path=":memory:"), Store(":memory:"))
    src = _Scripted(_items(), BLOCKED)
    await engine._run_source(src, None, get_region("KR"))
    assert (await engine._run_source(src, None, get_region("KR")))[1] is BLOCKED


def test_stale_source_is_a_warning_not_a_problem():
    h = Health()
    h.check_report("KR", {"clusters": [{}] * 20, "source_status": {
        "google_trends": {"ok": True, "error": None},
        "google_news": {"ok": True, "count": 2, "error": None, "stale": "HTTP 503 from https://news.google.com/rss"},
    }})
    assert h.ok
    assert any("google_news" in w and "직전 결과" in w for w in h.warnings)
