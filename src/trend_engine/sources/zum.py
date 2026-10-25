"""ZUM 'AI 이슈트렌드' — 키 없음, 한국 전용. zum.com 홈 페이지에 실린 데이터(issueWords)를 읽는다.

robots.txt 가 홈(`/$`)만 허용하므로 홈 한 장만 가져온다. 기사 묶음에서 뽑은 이슈 문구라
시그널·네이트(검색어)와 신호 성격이 달라 family 를 따로 둔다.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta

from ..models import TrendItem
from .base import Source, get_text_retry, rerank
from .local import BROWSER_UA
from .signal_bz import KOREA


class ZumIssue(Source):
    name = "zum_issue"
    label = "ZUM 이슈트렌드"
    kind = "keyword"
    weight = 0.8
    regions = KOREA
    fixture_ext = "html"
    stale_ok = timedelta(hours=2)
    _WORD = re.compile(r'"state":"(\w+)","corrected":\w+,"keyword":"((?:[^"\\]|\\.)*)"')

    async def fetch(self, client, region, settings):
        return await get_text_retry(client, "https://zum.com/", headers={"User-Agent": BROWSER_UA},
                                    retries=2, base_wait=5.0)

    def parse(self, raw, region):
        start = raw.find("issueWords")
        if start < 0:
            return []
        block = raw[start:].replace('\\"', '"')
        items: list[TrendItem] = []
        seen: set[str] = set()
        for state, escaped in self._WORD.findall(block):
            term = json.loads(f'"{escaped}"').strip()
            if not term or term in seen:
                continue
            seen.add(term)
            items.append(TrendItem(source=self.name, region=region, rank=0, keyword=term, kind="keyword",
                                   meta={"state": state}))
        return rerank(items)
