"""Wikimedia pageviews: keyless, absolute view counts, history back to 2015.

The `wikipedia` source reads one day — yesterday's most-read list. The same endpoints serve *any*
past day and any article's daily series, and that is what every history view here runs on: our own
archive is days deep, this one is years deep. Absolute counts also compare across countries, which
the 0–100 DataLab series cannot.

Endpoints (no key, courtesy User-Agent required):
  /top/{lang}.wikipedia/all-access/{Y/m/d}                      most-read articles that day
  /per-article/{lang}.wikipedia/all-access/user/{a}/daily/{s}/{e}   one article's daily views

Rate limits: share `wikimedia_gate` with the wikipedia source (concurrency 2 + pacing).
On 429/503, back off exponentially; never swallow the error — callers surface it.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
from datetime import date, timedelta
from typing import Any

import httpx

from .config import Settings
from .sources.base import SourceError, get_text
from .sources.wikipedia import UA, _SKIP_EXACT, _SKIP_PREFIX, wikimedia_gate
from .store import Store

REST = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
PACE = 0.25  # seconds between requests, per slot (shared CI IPs need more gap than a laptop)
SETTLED = timedelta(days=3)  # older days never change -> cache them for a year
FRESH = timedelta(hours=12)
RETRY_WAIT = 5.0  # seconds; Wikimedia throttles a burst of requests with 429


def _keep(article: str) -> bool:
    return article not in _SKIP_EXACT and not article.startswith(_SKIP_PREFIX) and ":" not in article


def parse_top(raw: str, limit: int = 200) -> list[tuple[str, int]]:
    """Pure: most-read response -> [(article, views)], portal/namespace noise removed."""
    data = json.loads(raw)
    items = data["items"][0]["articles"] if data.get("items") else []
    return [(a["article"], int(a.get("views", 0))) for a in items if _keep(a["article"])][:limit]


def parse_article(raw: str, start: date, end: date) -> list[tuple[date, int]]:
    """Pure: per-article response -> one (day, views) per day in range, missing days as 0."""
    data = json.loads(raw)
    by_day = {i["timestamp"][:8]: int(i.get("views", 0)) for i in data.get("items", [])}
    out, cur = [], start
    while cur <= end:
        out.append((cur, by_day.get(f"{cur:%Y%m%d}", 0)))
        cur += timedelta(days=1)
    return out


class History:
    """Cached reader for past pageviews. Offline mode reads tests/fixtures/pageviews/."""

    def __init__(self, settings: Settings, store: Store | None = None, budget: int | None = None):
        """`budget` caps how many *uncached* requests one pass may make. Past days are cached for a
        year, so a capped run simply fills in more history next time instead of blocking a deploy
        for twenty minutes on a cold cache."""
        self.settings = settings
        self.store = store
        self.budget = budget
        self.skipped = 0
        self._client: httpx.AsyncClient | None = None
        self.errors: list[str] = []  # anything that wasn't a plain 404 — surfaced, never swallowed

    # --- plumbing ----------------------------------------------------------------
    def _fixture(self, name: str) -> dict[str, Any]:
        path = self.settings.fixtures_dir / "pageviews" / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    async def _get(self, url: str, key: str, ttl: timedelta) -> str | None:
        if self.store is not None:
            hit = self.store.cache_get(key, ttl)
            if hit is not None:
                return hit
        if self.budget is not None:
            if self.budget <= 0:
                self.skipped += 1
                return None
            self.budget -= 1
        for attempt in range(4):
            try:
                # Same gate as sources.wikipedia so collect + history fill do not race.
                async with wikimedia_gate():
                    raw = await get_text(self._client, url, headers={"User-Agent": UA})
                    await asyncio.sleep(PACE)
            except SourceError as e:
                msg = str(e)
                if "HTTP 404" in msg:
                    return None  # normal: article too new, or that day was never published
                if ("HTTP 429" in msg or "HTTP 503" in msg) and attempt < 3:
                    await asyncio.sleep(RETRY_WAIT * (2 ** attempt))
                    continue
                self.errors.append(msg[:160])  # never swallow: callers report this
                return None
            if self.store is not None:
                self.store.cache_set(key, raw)
            return raw
        return None

    async def __aenter__(self) -> History:
        if not self.settings.offline:
            self._client = httpx.AsyncClient(timeout=self.settings.timeout)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # --- reads -------------------------------------------------------------------
    async def top(self, lang: str, day: date, limit: int = 200) -> list[tuple[str, int]]:
        if self.settings.offline:
            rows = self._fixture(f"{lang}-top").get(day.isoformat(), [])
            return [(a, int(v)) for a, v in rows if _keep(a)][:limit]
        ttl = timedelta(days=365) if date.today() - day > SETTLED else FRESH
        raw = await self._get(f"{REST}/top/{lang}.wikipedia/all-access/{day:%Y/%m/%d}",
                              f"pv:top:{lang}:{day.isoformat()}", ttl)
        return parse_top(raw, limit) if raw else []

    async def top_days(self, lang: str, days: list[date], limit: int = 200) -> dict[date, list[tuple[str, int]]]:
        got = await asyncio.gather(*(self.top(lang, d, limit) for d in days))
        return {d: rows for d, rows in zip(days, got) if rows}

    async def article(self, lang: str, name: str, start: date, end: date) -> list[tuple[date, int]]:
        if self.settings.offline:
            vals = self._fixture(f"{lang}-articles").get(name)
            return parse_article(json.dumps(vals), start, end) if vals else []
        q = urllib.parse.quote(name, safe="")
        raw = await self._get(f"{REST}/per-article/{lang}.wikipedia/all-access/user/{q}/daily/"
                              f"{start:%Y%m%d}/{end:%Y%m%d}",
                              f"pv:art:{lang}:{name}:{start.isoformat()}:{end.isoformat()}", FRESH)
        return parse_article(raw, start, end) if raw else []

    def latest_day(self, lang: str) -> date:
        """The most recent day we can read. Offline that is the newest day in the fixture, so a
        recorded snapshot keeps meaning the same thing however long it sits in the repo."""
        if self.settings.offline:
            days = sorted(self._fixture(f"{lang}-top"))
            if days:
                return date.fromisoformat(days[-1])
        return date.today() - timedelta(days=1)

    async def articles(self, lang: str, names: list[str], start: date, end: date
                       ) -> dict[str, list[tuple[date, int]]]:
        got = await asyncio.gather(*(self.article(lang, n, start, end) for n in names))
        return {n: s for n, s in zip(names, got) if s}


def days_back(n: int, today: date | None = None) -> list[date]:
    """The n settled days ending yesterday (today's list is still filling)."""
    end = (today or date.today()) - timedelta(days=1)
    return [end - timedelta(days=k) for k in range(n - 1, -1, -1)]
