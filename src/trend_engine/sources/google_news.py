"""Google News top stories RSS per country/language. Keyless. Content source (headlines)."""

from __future__ import annotations

from defusedxml import ElementTree as ET  # remote feeds: no XXE / entity expansion

from ..models import TrendItem
from .base import Source, get_text, rerank


class GoogleNews(Source):
    name = "google_news"
    label = "Google 뉴스"
    kind = "content"
    weight = 0.5
    fixture_ext = "xml"

    async def fetch(self, client, region, settings):
        hl, gl = region.lang, region.country
        return await get_text(client, f"https://news.google.com/rss?hl={hl}&gl={gl}&ceid={gl}:{hl}")

    def parse(self, raw, region):
        root = ET.fromstring(raw)
        items = []
        for node in root.iter("item"):
            title = (node.findtext("title") or "").strip()
            publisher = (node.findtext("source") or "").strip()
            if publisher and title.endswith(f" - {publisher}"):
                title = title[: -len(publisher) - 3].strip()
            if not title:
                continue
            items.append(
                TrendItem(
                    source=self.name,
                    region=region,
                    rank=0,
                    keyword=title,
                    kind="content",
                    url=node.findtext("link"),
                    meta={"publisher": publisher, "pub_date": node.findtext("pubDate")},
                )
            )
        return rerank(items)
