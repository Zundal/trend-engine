"""일본 전용 키 없는 소스 — KR 의 포털 이슈·로컬 차트 밀도를 맞추기 위한 묶음.

  yahoo_topics   야후 재팬 토픽 RSS (짧은 헤드라인 ≈ 포털 이슈 키워드)
  hatena         하테나 북마크 인기글 (소셜 관심)
  nicovideo      니코니코 24시간 랭킹 (젊은 층 영상)
  billboard_japan 빌보드 재팬 Hot 100 (국내 음악 ≈ 멜론 역할)
  livedoor_trend 라이브도어 트렌드 토픽
"""

from __future__ import annotations

import json
import re

from defusedxml import ElementTree as ET

from ..models import TrendItem
from .base import Source, get_text, rerank
from .local import BROWSER_UA, _rss_titles


class YahooTopics(Source):
    """야후 재팬 뉴스 토픽 — 짧은 헤드라인이라 keyword 로 넣어 구글 트렌드와 교차 검증한다."""

    name = "yahoo_topics"
    label = "일본 포털 토픽"
    kind = "keyword"
    weight = 0.85
    regions = frozenset({"JP"})
    fixture_ext = "json"
    FEEDS = ("top-picks", "domestic", "entertainment", "sports", "it")

    async def fetch(self, client, region, settings):
        out: dict[str, str] = {}
        for feed in self.FEEDS:
            out[feed] = await get_text(
                client, f"https://news.yahoo.co.jp/rss/topics/{feed}.xml",
                headers={"User-Agent": BROWSER_UA},
            )
        return json.dumps(out, ensure_ascii=False)

    def parse(self, raw, region):
        by_feed = json.loads(raw)
        seen: set[str] = set()
        items: list[TrendItem] = []
        for feed in self.FEEDS:
            for title in _rss_titles(by_feed.get(feed, ""), 8):
                if title in seen:
                    continue
                seen.add(title)
                # 토픽 제목은 '주제 설명' 꼴('台風 温帯低気圧になっても警戒を') — 앞 덩어리가 검색어 역할 (nate 의 query 처럼)
                head = title.split()[0] if " " in title or "\u3000" in title else ""
                items.append(TrendItem(
                    source=self.name, region=region, rank=0, keyword=title, kind="keyword",
                    meta={"section": feed, "query": head or None},
                ))
        return rerank(items)


class Hatena(Source):
    """하테나 북마크 인기 엔트리 — 일본에서 ‘지금 읽히는 글’ 신호."""

    name = "hatena"
    label = "일본 북마크 인기"
    kind = "content"
    weight = 0.4
    regions = frozenset({"JP"})
    fixture_ext = "xml"

    async def fetch(self, client, region, settings):
        return await get_text(
            client, "https://b.hatena.ne.jp/hotentry.rss",
            headers={"User-Agent": BROWSER_UA},
        )

    def parse(self, raw, region):
        root = ET.fromstring(raw)
        ns = "http://purl.org/rss/1.0/"
        items: list[TrendItem] = []
        for node in root.findall(f"{{{ns}}}item")[:30]:
            title = (node.findtext(f"{{{ns}}}title") or "").strip()
            link = (node.findtext(f"{{{ns}}}link") or "").strip() or None
            if not title:
                continue
            items.append(TrendItem(
                source=self.name, region=region, rank=0, keyword=title, kind="content",
                url=link, category="관심글",
            ))
        return rerank(items)


class NicoVideo(Source):
    """니코니코 종합 랭킹(24시간) — 일본 10·20대 영상 관심."""

    name = "nicovideo"
    label = "일본 영상 랭킹"
    kind = "content"
    weight = 0.45
    regions = frozenset({"JP"})
    fixture_ext = "json"

    async def fetch(self, client, region, settings):
        return await get_text(
            client,
            "https://nvapi.nicovideo.jp/v1/ranking/genre/all?term=24h&page=1",
            headers={
                "User-Agent": BROWSER_UA,
                "X-Frontend-Id": "6",
                "X-Frontend-Version": "0",
            },
        )

    def parse(self, raw, region):
        data = json.loads(raw)
        items: list[TrendItem] = []
        for row in ((data.get("data") or {}).get("items") or [])[:30]:
            title = (row.get("title") or "").strip()
            vid = row.get("id") or ""
            if not title:
                continue
            views = ((row.get("count") or {}).get("view"))
            items.append(TrendItem(
                source=self.name, region=region, rank=0, keyword=title, kind="content",
                volume=float(views) if views is not None else None,
                url=f"https://www.nicovideo.jp/watch/{vid}" if vid else None,
                category="영상",
            ))
        return rerank(items)


class BillboardJapan(Source):
    """빌보드 재팬 Hot 100 — 국내 음악·팬덤 신호 (한국 멜론에 대응)."""

    name = "billboard_japan"
    label = "일본 음악 차트"
    kind = "content"
    weight = 0.45
    regions = frozenset({"JP"})
    fixture_ext = "html"
    _SONG = re.compile(
        r'<p class="musuc_title">\s*([^<]+?)\s*</p>\s*<p class="artist_name">\s*<a[^>]*>([^<]+)</a>',
        re.S,
    )

    async def fetch(self, client, region, settings):
        return await get_text(
            client, "https://www.billboard-japan.com/charts/detail?a=hot100",
            headers={"User-Agent": BROWSER_UA, "Referer": "https://www.billboard-japan.com/"},
        )

    def parse(self, raw, region):
        items: list[TrendItem] = []
        for song, artist in self._SONG.findall(raw)[:50]:
            song, artist = song.strip(), artist.strip()
            if not song:
                continue
            items.append(TrendItem(
                source=self.name, region=region, rank=0, keyword=song, kind="content",
                category="음악",
                meta={"chart": "hot100", "artist": artist},
            ))
        return rerank(items)


class LivedoorTrend(Source):
    """라이브도어 트렌드 토픽 — 생활·이슈성 관심 제목."""

    name = "livedoor_trend"
    label = "일본 트렌드 토픽"
    kind = "content"
    weight = 0.4
    regions = frozenset({"JP"})
    fixture_ext = "xml"

    async def fetch(self, client, region, settings):
        return await get_text(
            client, "https://news.livedoor.com/topics/rss/trend.xml",
            headers={"User-Agent": BROWSER_UA},
        )

    def parse(self, raw, region):
        items = [
            TrendItem(
                source=self.name, region=region, rank=0, keyword=title, kind="content",
                category="토픽",
            )
            for title in _rss_titles(raw, 20)
        ]
        return rerank(items)
