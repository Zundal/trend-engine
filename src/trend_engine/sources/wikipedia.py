"""Wikipedia most-viewed articles (Wikimedia REST). Keyless. Per language, yesterday (UTC)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from ..config import get_region
from ..models import TrendItem
from .base import Source, SourceError, get_text, rerank

# Namespaces / evergreen pages that are traffic noise, not interest.
_SKIP_PREFIX = ("특수:", "위키백과:", "Special:", "Wikipedia:", "Main_Page", "特別:", "Wikipedia‐", "メインページ",
                "Spezial:", "Hauptseite", "Spécial:", "Portal:", "파일:", "File:", "분류:", "Category:", "틀:", "도움말:")
_SKIP_EXACT = {"대문", "-", "Main_Page", "Wikipedia"}


class Wikipedia(Source):
    name = "wikipedia"
    label = "위키백과 조회"
    weight = 0.4  # evergreen pages (방송사, 국가) add noise; low weight

    async def fetch(self, client, region, settings):
        # Daily data lands with a delay; try yesterday, then the day before.
        last_err = None
        for back in (1, 2):
            day = datetime.now(timezone.utc) - timedelta(days=back)
            url = (
                "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
                f"{region.lang}.wikipedia/all-access/{day:%Y/%m/%d}"
            )
            try:
                return await get_text(client, url)
            except SourceError as e:
                last_err = e
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
