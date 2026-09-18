"""signal.bz 실시간 검색어 (네이버 실검 폐지 후 포털 이슈 키워드 집계). Keyless, Korea only. Unofficial endpoint."""

from __future__ import annotations

import json

from ..models import TrendItem
from .base import Source, get_text, rerank

KOREA = frozenset({"KR", "KR-11"})


class SignalBz(Source):
    name = "signal_bz"
    label = "시그널 실시간"
    weight = 0.9
    regions = KOREA
    family = "portal_realtime"

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://api.signal.bz/news/realtime")

    def parse(self, raw, region):
        data = json.loads(raw)
        items = [
            TrendItem(
                source=self.name,
                region=region,
                rank=int(row.get("rank") or 0),
                keyword=str(row["keyword"]).strip(),
                meta={"state": row.get("state")},
            )
            for row in data.get("top10", [])
            if row.get("keyword")
        ]
        items.sort(key=lambda i: i.rank)
        return rerank(items)
