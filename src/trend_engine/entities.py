"""같은 것을 나라마다 무엇이라 부르는가 — keyless entity alignment across languages.

Comparing countries by keyword is hopeless: 오징어 게임 / イカゲーム / Squid Game / 魷魚遊戲系列 are
one thing with four names, and no amount of string similarity will join them. Wikidata already
holds that join (one item, one sitelink per wiki) and serves it without a key, 50 titles per call.

With the join in hand, and pageviews being absolute counts rather than a 0–100 index, the same
transfer kernel that measures a handover between age groups can measure one between countries.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import timedelta
from typing import Any

from .config import Settings
from .sources.base import SourceError, get_text
from .store import Store

API = "https://www.wikidata.org/w/api.php"
UA = "trend-engine/0.1 (https://github.com/Zundal/trend-engine)"
BATCH = 50  # wbgetentities' limit for anonymous callers
TTL = timedelta(days=30)  # an article's interlanguage links barely move


def parse_sitelinks(raw: str, langs: list[str]) -> dict[str, dict[str, str]]:
    """Pure: wbgetentities response -> {qid: {lang: title}} for the languages we asked about."""
    data = json.loads(raw)
    out: dict[str, dict[str, str]] = {}
    for qid, ent in (data.get("entities") or {}).items():
        if qid.startswith("-") or "sitelinks" not in ent:  # "-1" = title not found
            continue
        links = {lang: ent["sitelinks"][f"{lang}wiki"]["title"]
                 for lang in langs if f"{lang}wiki" in ent["sitelinks"]}
        if len(links) >= 2:  # an entity only one wiki knows about can't cross a border
            out[qid] = links
    return out


class Entities:
    """Title -> Wikidata item -> the same article's title in other languages. Cached for a month."""

    def __init__(self, settings: Settings, store: Store | None = None):
        self.settings = settings
        self.store = store
        self._client = None
        self.errors: list[str] = []

    async def __aenter__(self) -> Entities:
        if not self.settings.offline:
            import httpx

            self._client = httpx.AsyncClient(timeout=self.settings.timeout)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _fixture(self) -> dict[str, Any]:
        path = self.settings.fixtures_dir / "entities" / "sitelinks.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    async def align(self, titles: list[str], from_lang: str, langs: list[str]) -> dict[str, dict[str, str]]:
        """-> {qid: {lang: title}}, only entities that exist in at least two of `langs`."""
        if self.settings.offline:
            fx = self._fixture().get(from_lang, {})
            return {qid: links for qid, links in fx.items()
                    if links.get(from_lang) in set(titles) and len(links) >= 2}
        out: dict[str, dict[str, str]] = {}
        for i in range(0, len(titles), BATCH):
            batch = [t for t in titles[i: i + BATCH] if t]
            if not batch:
                continue
            key = f"wd:{from_lang}:{','.join(sorted(langs))}:" + "|".join(sorted(batch))
            raw = self.store.cache_get(key, TTL) if self.store else None
            if raw is None:
                params = {"action": "wbgetentities", "sites": f"{from_lang}wiki",
                          "titles": "|".join(batch), "props": "sitelinks", "format": "json"}
                try:
                    raw = await get_text(self._client, f"{API}?{urllib.parse.urlencode(params)}",
                                         headers={"User-Agent": UA})
                except SourceError as e:
                    self.errors.append(str(e)[:160])
                    continue
                if self.store:
                    self.store.cache_set(key, raw)
            out |= parse_sitelinks(raw, langs)
        return out
