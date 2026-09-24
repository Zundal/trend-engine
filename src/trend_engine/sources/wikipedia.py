"""Wikipedia most-viewed articles (Wikimedia REST). Keyless. Per language, yesterday (UTC)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

from ..config import get_region
from ..models import TrendItem
from .base import Source, SourceError, get_text_retry, rerank

# Courtesy User-Agent required by Wikimedia; also used by pageviews.History.
UA = "trend-engine/0.1 (https://github.com/Zundal/trend-engine)"
# Shared with pageviews.History so the hourly export does not stampede the same IP.
CONCURRENCY = 2  # measured: 6 in parallel earns 429s from a datacenter IP
_GATE: asyncio.Semaphore | None = None


def wikimedia_gate() -> asyncio.Semaphore:
    global _GATE
    if _GATE is None:
        _GATE = asyncio.Semaphore(CONCURRENCY)
    return _GATE


# Namespaces / evergreen pages that are traffic noise, not interest.
_SKIP_PREFIX = ("특수:", "위키백과:", "Special:", "Wikipedia:", "Main_Page", "特別:", "Wikipedia‐", "メインページ",
                "Spezial:", "Hauptseite", "Spécial:", "Portal:", "파일:", "File:", "분류:", "Category:", "틀:", "도움말:")
_SKIP_EXACT = {"대문", "-", "Main_Page", "Wikipedia"}


class Wikipedia(Source):
    name = "wikipedia"
    label = "위키백과 조회"
    optional = False
    weight = 0.4  # evergreen pages (방송사, 국가) add noise; low weight

    async def fetch(self, client, region, settings):
        # Daily data lands with a delay; try yesterday, then the day before (404 only).
        # 429 must not burn a second day request — that makes the throttle worse.
        last_err = None
        for back in (1, 2):
            day = datetime.now(timezone.utc) - timedelta(days=back)
            url = (
                "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
                f"{region.lang}.wikipedia/all-access/{day:%Y/%m/%d}"
            )
            try:
                async with wikimedia_gate():
                    return await get_text_retry(
                        client, url, headers={"User-Agent": UA}, retries=3, base_wait=5.0
                    )
            except SourceError as e:
                last_err = e
                if "HTTP 404" not in str(e):
                    raise
        raise last_err  # type: ignore[misc]

    def parse(self, raw, region):
        data = json.loads(raw)
        articles = data["items"][0]["articles"] if data.get("items") else []
        lang = get_region(region).lang
        items = []
        for a in articles:
            title = a["article"]
            if title in _SKIP_EXACT or title.startswith(_SKIP_PREFIX) or ":" in title:
                continue
            items.append(
                TrendItem(
                    source=self.name,
                    region=region,
                    rank=0,
                    keyword=title.replace("_", " "),
                    volume=float(a.get("views", 0)),
                    url=f"https://{lang}.wikipedia.org/wiki/{title}",
                    # '강신철 (군인)' -> '강신철' as the search query
                    meta={"query": re.sub(r"\s*\(.*?\)\s*", " ", title.replace("_", " ")).strip()},
                )
            )
            if len(items) >= 30:
                break
        return rerank(items)
