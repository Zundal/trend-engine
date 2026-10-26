"""X(트위터) 나라별 실시간 트렌드 — 키 없는 공개 페이지 두 곳.

  trends24         (JP) trends24.in 의 최신 시간대 목록
  getdaytrends     (US·GB) getdaytrends.com 의 '지금' 목록 (trends24 는 배포 서버 IP 를 403 으로 막는다)
  yahoo_realtime   (JP) 야후 재팬 실시간 검색 '트렌드' (X 게시물 기반)

모두 X 에서 나온 신호라 family 를 같게 둔다 — 같은 신호가 두 번 세지지 않게.
키 없는 포털 인기 검색어가 없던 미국·영국·일본에 '지금 사람들이 말하는 것' 키워드 축을 준다.
한국·베트남은 팬덤 해시태그가 대부분이라 뺐다 (docs/SOURCES.md).
"""

from __future__ import annotations

import html
import re
from datetime import timedelta
from urllib.parse import unquote

from ..models import TrendItem
from .base import Source, get_text_retry, rerank
from .local import BROWSER_UA

X_FAMILY = "x_trends"
# KR/VN lists are mostly fan-campaign hashtags (VN: Thai drama tags) and displaced
# cross-confirmed issues in live measurement; Taiwan has no page (404).
# trends24 answers GitHub Actions IPs with a Cloudflare 403 for US/GB, so those use getdaytrends.
SLUGS = {"US": "united-states", "JP": "japan", "GB": "united-kingdom"}


class Trends24(Source):
    """trends24.in — 나라별 X 트렌드. 페이지에 시간대별 목록이 쌓여 있어 맨 앞(최신) 목록만 쓴다."""

    name = "trends24"
    label = "X 실시간 트렌드"
    kind = "keyword"
    weight = 0.7  # 대화량 기반이라 검색량보다 잡음이 많다 (인사말·일반 단어)
    family = X_FAMILY
    regions = frozenset({"JP"})
    fixture_ext = "html"
    stale_ok = timedelta(hours=2)
    LIMIT = 30
    _LIST = re.compile(r"<ol class=trend-card__list>(.*?)</ol>", re.S)
    _LINK = re.compile(r"class=trend-link>([^<]+)</a>")

    async def fetch(self, client, region, settings):
        return await get_text_retry(client, f"https://trends24.in/{SLUGS[region.country]}/",
                                    headers={"User-Agent": BROWSER_UA}, retries=2, base_wait=5.0)

    def _names(self, raw):
        latest = self._LIST.search(raw)
        return self._LINK.findall(latest.group(1)) if latest else []

    def parse(self, raw, region):
        items: list[TrendItem] = []
        seen: set[str] = set()
        for name in self._names(raw):
            term = html.unescape(name).strip().lstrip("#").replace("_", " ").strip()
            if not term or term.lower() in seen:
                continue
            seen.add(term.lower())
            items.append(TrendItem(source=self.name, region=region, rank=0, keyword=term, kind="keyword",
                                   meta={"hashtag": name.strip().startswith("#")}))
            if len(items) >= self.LIMIT:
                break
        return rerank(items)


class GetDayTrends(Trends24):
    """getdaytrends.com — 같은 X 트렌드. '지금' 목록(상위 15 + 접힌 나머지)만 쓰고 아래 'Top Hashtags' 집계는 버린다."""

    name = "getdaytrends"
    regions = frozenset({"US", "GB"})
    _TABLE = re.compile(r'<table class="[^"]*ranking trends[^"]*"[^>]*>(.*?)</table>', re.S)
    _LINK = re.compile(r'<a class="string" href="[^"]*">([^<]+)</a>')

    async def fetch(self, client, region, settings):
        return await get_text_retry(client, f"https://getdaytrends.com/{SLUGS[region.country]}/",
                                    headers={"User-Agent": BROWSER_UA}, retries=2, base_wait=5.0)

    def _names(self, raw):
        return [n for table in self._TABLE.findall(raw) for n in self._LINK.findall(table)]


class YahooRealtimeJP(Source):
    """야후 재팬 실시간 검색 '트렌드' 20개 — 일본에서 X 화제어를 가장 깔끔하게 순위로 준다."""

    name = "yahoo_realtime"
    label = "일본 실시간 트렌드"
    kind = "keyword"
    weight = 0.75
    family = X_FAMILY
    regions = frozenset({"JP"})
    fixture_ext = "html"
    _ATK = re.compile(r'href="/realtime/search\?p=([^&"]+)[^"]*" data-cl-params="_cl_link:atk;_cl_position:(\d+)"')

    async def fetch(self, client, region, settings):
        return await get_text_retry(client, "https://search.yahoo.co.jp/realtime",
                                    headers={"User-Agent": BROWSER_UA}, retries=2, base_wait=5.0)

    def parse(self, raw, region):
        rows = sorted({int(pos): unquote(q).strip() for q, pos in self._ATK.findall(raw)}.items())
        return rerank([TrendItem(source=self.name, region=region, rank=0, keyword=term, kind="keyword")
                       for _, term in rows if term])
