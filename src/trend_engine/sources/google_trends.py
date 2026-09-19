"""Google Trends 'Trending now' RSS. Keyless. Any geo, including sub-regions like KR-11 (Seoul)."""

from __future__ import annotations

import re
from defusedxml import ElementTree as ET  # remote feeds: no XXE / entity expansion

from ..models import TrendItem
from .base import Source, get_text, rerank

HT = "{https://trends.google.com/trending/rss}"


def parse_traffic(text: str | None) -> float | None:
    """'200+' -> 200, '2,000+' -> 2000, '10K+' -> 10000, '1M+' -> 1_000_000."""
    if not text:
        return None
    m = re.match(r"([\d.,]+)\s*([KkMm]?)", text.strip())
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return n * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1)


class GoogleTrends(Source):
    name = "google_trends"
    label = "Google 트렌드"
    weight = 1.0
    fixture_ext = "xml"
    subregion_aware = True

    async def fetch(self, client, region, settings):
        return await get_text(client, f"https://trends.google.com/trending/rss?geo={region.code}")

    def parse(self, raw, region):
        root = ET.fromstring(raw)
        items = []
        for node in root.iter("item"):
            title = (node.findtext("title") or "").strip()
            if not title:
                continue
            news = [
                (n.findtext(f"{HT}news_item_title") or "").strip()
                for n in node.findall(f"{HT}news_item")
            ]
            first_url = next(
                (n.findtext(f"{HT}news_item_url") for n in node.findall(f"{HT}news_item")), None
            )
            items.append(
                TrendItem(
                    source=self.name,
                    region=region,
                    rank=0,
                    keyword=title,
                    volume=parse_traffic(node.findtext(f"{HT}approx_traffic")),
                    url=first_url,
                    related=[t for t in news if t],
                    meta={"pub_date": node.findtext("pubDate"), "picture": node.findtext(f"{HT}picture")},
                )
            )
        # RSS order is recency, not size: rank by approximate traffic (stable for ties).
        items.sort(key=lambda i: -(i.volume or 0))
        return rerank(items)
