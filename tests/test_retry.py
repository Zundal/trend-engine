"""Transient upstream 429/503 must be retried — otherwise the hourly Pages alert goes red."""

from __future__ import annotations

import httpx
import pytest

from trend_engine.config import get_region
from trend_engine.pageviews import History
from trend_engine.sources.base import SourceError, get_text_retry
from trend_engine.sources.google_news import GoogleNews
from trend_engine.sources.wikipedia import Wikipedia


class _SeqTransport(httpx.AsyncBaseTransport):
    """Return canned responses in order; records every request URL."""

    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if not self.responses:
            raise AssertionError(f"unexpected request: {request.url}")
        resp = self.responses.pop(0)
        return httpx.Response(resp.status_code, headers=resp.headers, text=resp.text, request=request)


@pytest.mark.asyncio
async def test_get_text_retry_recovers_from_429(monkeypatch):
    monkeypatch.setattr("trend_engine.sources.base.asyncio.sleep", _instant_sleep)
    transport = _SeqTransport([
        httpx.Response(429, headers={"Retry-After": "0"}, text="slow down"),
        httpx.Response(200, text='{"ok": true}'),
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        body = await get_text_retry(client, "https://example.test/x", retries=2, base_wait=0.01)
    assert body == '{"ok": true}'
    assert len(transport.urls) == 2


@pytest.mark.asyncio
async def test_get_text_retry_gives_up_after_budget(monkeypatch):
    monkeypatch.setattr("trend_engine.sources.base.asyncio.sleep", _instant_sleep)
    transport = _SeqTransport([httpx.Response(503, text="nope")] * 4)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SourceError, match="HTTP 503"):
            await get_text_retry(client, "https://example.test/x", retries=2, base_wait=0.01)
    assert len(transport.urls) == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_wikipedia_retries_same_day_instead_of_burning_fallback(monkeypatch):
    """A 429 on yesterday must not immediately request the day before — that worsens the throttle."""
    monkeypatch.setattr("trend_engine.sources.base.asyncio.sleep", _instant_sleep)
    ok = '{"items":[{"articles":[{"article":"손흥민","views":100}]}]}'
    transport = _SeqTransport([
        httpx.Response(429, text="too many"),
        httpx.Response(200, text=ok),
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        raw = await Wikipedia().fetch(client, get_region("KR"), None)
    assert "손흥민" in raw
    days = {u.rstrip("/").split("/")[-1] for u in transport.urls}
    assert len(days) == 1  # only one calendar day was asked for


@pytest.mark.asyncio
async def test_wikipedia_404_falls_back_to_previous_day(monkeypatch):
    monkeypatch.setattr("trend_engine.sources.base.asyncio.sleep", _instant_sleep)
    ok = '{"items":[{"articles":[{"article":"손흥민","views":100}]}]}'
    transport = _SeqTransport([
        httpx.Response(404, text="not published"),
        httpx.Response(200, text=ok),
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        raw = await Wikipedia().fetch(client, get_region("KR"), None)
    assert "손흥민" in raw
    assert len(transport.urls) == 2


@pytest.mark.asyncio
async def test_google_news_retries_503(monkeypatch):
    monkeypatch.setattr("trend_engine.sources.base.asyncio.sleep", _instant_sleep)
    transport = _SeqTransport([
        httpx.Response(503, text="Sorry..."),
        httpx.Response(200, text="<rss><channel></channel></rss>"),
    ])
    async with httpx.AsyncClient(transport=transport) as client:
        raw = await GoogleNews().fetch(client, get_region("US"), None)
    assert "<rss>" in raw
    assert len(transport.urls) == 2


@pytest.mark.asyncio
async def test_pageviews_history_retries_429(monkeypatch, tmp_path):
    monkeypatch.setattr("trend_engine.pageviews.asyncio.sleep", _instant_sleep)
    from trend_engine.config import Settings

    transport = _SeqTransport([
        httpx.Response(429, text="slow"),
        httpx.Response(200, text='{"items":[{"articles":[{"article":"A","views":9}]}]}'),
    ])
    settings = Settings(offline=False, fixtures_dir=tmp_path)
    async with History(settings, store=None) as hist:
        hist._client = httpx.AsyncClient(transport=transport)
        rows = await hist.top("ko", __import__("datetime").date(2026, 9, 22), limit=5)
        await hist._client.aclose()
    assert rows == [("A", 9)]
    assert len(transport.urls) == 2


async def _instant_sleep(_delay: float) -> None:
    return None
