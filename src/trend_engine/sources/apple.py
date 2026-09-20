"""Apple charts per country (keyless): most-played songs and top free apps.

Every country we cover has one, which matters because outside Korea we have no age data — music and
app charts skew young, so they widen the 10·20대 picture and feed the category classifier (음악 / 앱).
Content source: chart entries don't rank as trends themselves, they corroborate keywords.
"""

from __future__ import annotations

import json

from ..models import TrendItem
from .base import Source, get_text, rerank

FEEDS = (("topsongs", "음악"), ("topfreeapplications", "테크·IT"))
LIMIT = 20


class AppleCharts(Source):
    name = "apple_charts"
    label = "인기 차트"
    kind = "content"
    weight = 0.4

    async def fetch(self, client, region, settings):
        out = {}
        for feed, _ in FEEDS:
            url = f"https://itunes.apple.com/{region.country.lower()}/rss/{feed}/limit={LIMIT}/json"
            out[feed] = await get_text(client, url)
        return json.dumps(out, ensure_ascii=False)

    def parse(self, raw, region):
        by_feed = json.loads(raw)
        items: list[TrendItem] = []
        for feed, category in FEEDS:
            entries = (json.loads(by_feed[feed]) if isinstance(by_feed.get(feed), str) else by_feed.get(feed, {}))
            for e in (entries.get("feed", {}) or {}).get("entry", []) or []:
                name = (e.get("im:name", {}) or {}).get("label", "").strip()
                artist = (e.get("im:artist", {}) or {}).get("label", "").strip()
                if not name:
                    continue
                items.append(TrendItem(
                    source=self.name, region=region, rank=0, keyword=name, kind="content",
                    url=(e.get("id", {}) or {}).get("label"), category=category,
                    related=[artist] if artist else [],
                    meta={"chart": feed, "artist": artist},
                ))
        return rerank(items)
