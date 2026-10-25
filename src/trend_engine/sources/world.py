"""미국·영국·대만·베트남 키 없는 로컬 소스 — 일본(japan.py)처럼 나라별 밀도를 한국에 가깝게.

  billboard_us     (US) Billboard Hot 100 HTML
  yahoo_us         (US) 야후 미국 뉴스 RSS
  official_charts  (GB) Official Singles Chart HTML
  bbc_news         (GB) BBC 뉴스 RSS
  kkbox_tw         (TW) KKBOX 일간 차트 JSON (멜론 역할)
  yahoo_tw_search  (TW) 야후 대만 홈 인기 검색어 (keyword, 광고 제외)
  yahoo_tw         (TW) 야후 대만 뉴스 RSS
  gnn_tw           (TW) 바하무트 GNN 게임 뉴스 RSS
  vnexpress        (VN) VnExpress 많이 본 뉴스 RSS
"""

from __future__ import annotations

import html
import json
import re

from ..models import TrendItem
from .base import Source, get_text, rerank
from .local import BROWSER_UA, _rss_titles


def _clean(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _rss_source(name_: str, label_: str, region: str, url: str, category: str, limit: int = 25, weight_: float = 0.4):
    class _Rss(Source):
        name = name_
        label = label_
        kind = "content"
        weight = weight_
        regions = frozenset({region})
        fixture_ext = "xml"

        async def fetch(self, client, region, settings):
            return await get_text(client, url, headers={"User-Agent": BROWSER_UA})

        def parse(self, raw, region):
            return rerank([TrendItem(source=self.name, region=region, rank=0, keyword=t, kind="content",
                                     category=category) for t in _rss_titles(raw, limit)])

    _Rss.__name__ = _Rss.__qualname__ = "".join(p.title() for p in name_.split("_"))
    return _Rss


class BillboardUS(Source):
    """Billboard Hot 100 — 미국 음악 차트 (한국 멜론에 대응)."""

    name = "billboard_us"
    label = "미국 음악 차트"
    kind = "content"
    weight = 0.45
    regions = frozenset({"US"})
    fixture_ext = "html"
    _ROW = re.compile(r'<h3 id="title-of-a-story" class="c-title[^"]*">([^<]*)</h3>\s*<span class="\s*c-label a-no-trucate[^"]*">(.*?)</span>', re.S)

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://www.billboard.com/charts/hot-100/", headers={"User-Agent": BROWSER_UA})

    def parse(self, raw, region):
        items = [TrendItem(source=self.name, region=region, rank=0, keyword=_clean(t), kind="content",
                           category="음악", meta={"chart": "hot100", "artist": _clean(a)})
                 for t, a in self._ROW.findall(raw)[:50] if _clean(t)]
        return rerank(items)


class OfficialCharts(Source):
    """영국 Official Singles Chart Top 100."""

    name = "official_charts"
    label = "영국 음악 차트"
    kind = "content"
    weight = 0.45
    regions = frozenset({"GB"})
    fixture_ext = "html"
    _TITLE = re.compile(r'<a[^>]*class="chart-name[^"]*"[^>]*>(.*?)</a>', re.S)
    _ARTIST = re.compile(r'<a[^>]*class="chart-artist[^"]*"[^>]*>(.*?)</a>', re.S)

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://www.officialcharts.com/charts/singles-chart/",
                              headers={"User-Agent": BROWSER_UA})

    def parse(self, raw, region):
        titles = [_clean(re.sub(r"<span[^>]*>\s*New\s*</span>", "", t)) for t in self._TITLE.findall(raw)]
        artists = [_clean(a) for a in self._ARTIST.findall(raw)]
        items = [TrendItem(source=self.name, region=region, rank=0, keyword=t.title(), kind="content",
                           category="음악", meta={"chart": "singles", "artist": a.title()})
                 for t, a in list(zip(titles, artists))[:50] if t]
        return rerank(items)


class KKBoxTW(Source):
    """KKBOX 대만 일간 종합 차트 — 대만 10·20대 음악 신호."""

    name = "kkbox_tw"
    label = "대만 음악 차트"
    kind = "content"
    weight = 0.45
    regions = frozenset({"TW"})
    fixture_ext = "json"

    async def fetch(self, client, region, settings):
        return await get_text(
            client, "https://kma.kkbox.com/charts/api/v1/daily?category=297&lang=tc&limit=50&terr=tw&type=song",
            headers={"User-Agent": BROWSER_UA})

    def parse(self, raw, region):
        songs = ((json.loads(raw).get("data") or {}).get("charts") or {}).get("song") or []
        items = [TrendItem(source=self.name, region=region, rank=0, keyword=s["song_name"].strip(), kind="content",
                           url=s.get("song_url"), category="음악",
                           meta={"chart": "daily", "artist": (s.get("artist_name") or "").strip()})
                 for s in songs[:50] if (s.get("song_name") or "").strip()]
        return rerank(items)


class YahooTWSearch(Source):
    """야후 대만 홈 '熱搜' — 대만 포털 인기 검색어 (한국 signal/nate 역할). 유료 노출(kt:rev)은 버린다."""

    name = "yahoo_tw_search"
    label = "대만 포털 인기 검색어"
    kind = "keyword"
    weight = 0.85
    regions = frozenset({"TW"})
    fixture_ext = "html"
    _YLK = re.compile(r'data-ylk="([^"]*subsec:srch-tts;[^"]*)"')

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://tw.yahoo.com/", headers={"User-Agent": BROWSER_UA})

    def parse(self, raw, region):
        items: list[TrendItem] = []
        seen: set[str] = set()
        for m in self._YLK.finditer(raw):
            kv = dict(p.split(":", 1) for p in html.unescape(m.group(1)).split(";") if ":" in p)
            term = (kv.get("tts-term") or "").strip()
            if not term or kv.get("kt") != "org" or term in seen:
                continue
            seen.add(term)
            items.append(TrendItem(source=self.name, region=region, rank=0, keyword=term, kind="keyword"))
        return rerank(items)


YahooUS = _rss_source("yahoo_us", "미국 포털 뉴스", "US", "https://news.yahoo.com/rss/", "뉴스")
BBCNews = _rss_source("bbc_news", "영국 뉴스", "GB", "https://feeds.bbci.co.uk/news/rss.xml", "뉴스")
YahooTW = _rss_source("yahoo_tw", "대만 포털 뉴스", "TW", "https://tw.news.yahoo.com/rss/", "뉴스", limit=30)
GnnTW = _rss_source("gnn_tw", "대만 게임 뉴스", "TW", "https://gnn.gamer.com.tw/rss.xml", "게임")
VnExpress = _rss_source("vnexpress", "베트남 많이 본 뉴스", "VN", "https://vnexpress.net/rss/tin-xem-nhieu.rss", "뉴스", limit=30)
