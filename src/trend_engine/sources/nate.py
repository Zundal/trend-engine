"""Nate 실시간 이슈 키워드. Keyless, Korea only. Unofficial JS data file (EUC-KR).

Row shape: [rank, headline, state(s/n/+/-), change, short_query]
"""

from __future__ import annotations

import json
import re

from ..models import TrendItem
from .base import Source, get_text, rerank
from .signal_bz import KOREA


class Nate(Source):
    name = "nate"
    label = "네이트 실시간"
    optional = False
    weight = 0.9
    regions = KOREA
    family = "portal_realtime"
    fixture_ext = "js"

    async def fetch(self, client, region, settings):
        return await get_text(
            client,
            "https://www.nate.com/js/data/jsonLiveKeywordDataV1.js?v=1",
            encoding="euc-kr",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.nate.com/"},
        )

    def parse(self, raw, region):
        m = re.search(r"\[\s*\[.*\]\s*\]", raw, re.S)
        if not m:
            return []
        rows = json.loads(m.group(0))
        items = []
        for row in rows:
            if len(row) < 2 or not str(row[1]).strip():
                continue
            query = str(row[4]).strip() if len(row) > 4 else ""
            items.append(
                TrendItem(
                    source=self.name,
                    region=region,
                    rank=int(row[0]),
                    keyword=str(row[1]).strip(),
                    meta={"state": row[2] if len(row) > 2 else None, "query": query or None},
                )
            )
        items.sort(key=lambda i: i.rank)
        return rerank(items)
