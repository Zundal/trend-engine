"""Country-specific keyless sources — the platforms young people actually use in each country.

Outside Korea we have no age data, so the next best thing is *where* the signal comes from: a
community or chart that skews young. All of these work without an API key (that is the project rule).

  pixiv   (JP)  daily illustration ranking — anime/game fandom, heavily 10·20대
  ettoday (TW)  ETtoday 星光雲 (entertainment) + game sections — PTT blocks datacenter IPs (see PTT below)
  reddit  (US/GB) r/teenagers + r/GenZ hot posts
  kenh14  (VN)  youth news outlet
  steam   (all) most-played games (global list; gaming context every country shares)
"""

from __future__ import annotations

import json
import re

from defusedxml import ElementTree as ET

from ..models import TrendItem
from .base import Source, get_text, rerank

BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"


def _rss_titles(raw: str, limit: int = 25) -> list[str]:
    root = ET.fromstring(raw)
    out = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        if title:
            out.append(title)
        if len(out) >= limit:
            break
    return out


class Pixiv(Source):
    """일본 10·20대 창작 커뮤니티의 일간 랭킹 — 제목과 태그가 애니·게임 유행을 보여준다."""

    name = "pixiv"
    label = "일본 창작 랭킹"
    kind = "content"
    weight = 0.4
    regions = frozenset({"JP"})

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://www.pixiv.net/ranking.php?mode=daily&format=json&p=1",
                              headers={"User-Agent": BROWSER_UA, "Referer": "https://www.pixiv.net/"})

    def parse(self, raw, region):
        data = json.loads(raw)
        items = []
        for c in (data.get("contents") or [])[:30]:
            title = (c.get("title") or "").strip()
            if not title:
                continue
            items.append(TrendItem(source=self.name, region=region, rank=0, keyword=title, kind="content",
                                   related=[t for t in (c.get("tags") or [])][:8],
                                   meta={"user": c.get("user_name")}))
        return rerank(items)


class ETtoday(Source):
    """대만 ETtoday 연예(星光雲)·게임 섹션 — 대만 젊은 층이 많이 보는 기사."""

    name = "ettoday"
    label = "대만 연예·게임"
    kind = "content"
    weight = 0.4
    regions = frozenset({"TW"})
    fixture_ext = "json"
    FEEDS = (("star", "연예·방송"), ("game", "게임"))

    async def fetch(self, client, region, settings):
        out = {}
        for feed, _ in self.FEEDS:
            out[feed] = await get_text(client, f"https://feeds.feedburner.com/ettoday/{feed}",
                                       headers={"User-Agent": BROWSER_UA})
        return json.dumps(out, ensure_ascii=False)

    def parse(self, raw, region):
        by_feed = json.loads(raw)
        items = []
        for feed, category in self.FEEDS:
            for title in _rss_titles(by_feed.get(feed, ""), 25):
                items.append(TrendItem(source=self.name, region=region, rank=0, keyword=title, kind="content",
                                       category=category, meta={"section": feed}))
        return rerank(items)


class PTT(Source):
    """대만 PTT C_Chat(애니·게임) 인기글. 로컬에서는 되지만 **Cloudflare 가 데이터센터 IP(GitHub Actions)를
    403 으로 막는다** — 레지스트리에서 빼두고, 자체 서버에서 돌릴 때만 등록해서 쓸 것."""

    name = "ptt"
    label = "대만 커뮤니티"
    kind = "content"
    weight = 0.4
    regions = frozenset({"TW"})
    fixture_ext = "html"

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://www.ptt.cc/bbs/C_Chat/index.html",
                              headers={"User-Agent": BROWSER_UA, "Cookie": "over18=1"})

    def parse(self, raw, region):
        titles = re.findall(r'class="title">\s*<a href="[^"]+">([^<]+)</a>', raw)
        items = [TrendItem(source=self.name, region=region, rank=0, keyword=t.strip(), kind="content")
                 for t in titles if t.strip() and "本文已被刪除" not in t]
        return rerank(items)


class Reddit(Source):
    """영어권 10·20대 서브레딧(r/teenagers, r/GenZ)의 인기 글.

    US 에만 붙인다: 내용이 영국과 같은데 익명 요청은 분당 한도가 낮아 두 번 부르면 429 가 난다."""

    name = "reddit"
    label = "영어권 커뮤니티"
    kind = "content"
    weight = 0.4
    regions = frozenset({"US"})
    fixture_ext = "xml"

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://www.reddit.com/r/teenagers+GenZ/hot/.rss?limit=30",
                              headers={"User-Agent": BROWSER_UA})

    def parse(self, raw, region):
        root = ET.fromstring(raw)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items = []
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", default="", namespaces=ns) or "").strip()
            link = e.find("a:link", ns)
            if title:
                items.append(TrendItem(source=self.name, region=region, rank=0, keyword=title, kind="content",
                                       url=link.get("href") if link is not None else None))
        return rerank(items)


class Kenh14(Source):
    """베트남 젊은 층 매체."""

    name = "kenh14"
    label = "베트남 청년 매체"
    kind = "content"
    weight = 0.4
    regions = frozenset({"VN"})
    fixture_ext = "xml"

    async def fetch(self, client, region, settings):
        return await get_text(client, "https://kenh14.vn/rss/home.rss", headers={"User-Agent": BROWSER_UA})

    def parse(self, raw, region):
        items = [TrendItem(source=self.name, region=region, rank=0, keyword=t, kind="content")
                 for t in _rss_titles(raw, 30)]
        return rerank(items)


class Steam(Source):
    """가장 많이 플레이된 게임 (전 세계 공통 목록) — 게임 분야 신호."""

    name = "steam"
    label = "게임 순위"
    kind = "content"
    weight = 0.35
    TOP = 12

    async def fetch(self, client, region, settings):
        raw = await get_text(client, "https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/")
        ranks = (json.loads(raw).get("response", {}) or {}).get("ranks", [])[: self.TOP]
        named = []
        for r in ranks:  # the chart gives ids only; resolve names (small, keyless)
            try:
                d = json.loads(await get_text(
                    client, f"https://store.steampowered.com/api/appdetails?appids={r['appid']}&filters=basic"))
                name = ((d.get(str(r["appid"])) or {}).get("data") or {}).get("name")
            except Exception:  # noqa: BLE001 — a missing name must not break the source
                name = None
            named.append({"rank": r.get("rank"), "appid": r.get("appid"), "name": name,
                          "peak": r.get("peak_in_game")})
        return json.dumps({"games": named}, ensure_ascii=False)

    def parse(self, raw, region):
        items = []
        for g in json.loads(raw).get("games", []):
            if g.get("name"):
                items.append(TrendItem(source=self.name, region=region, rank=0, keyword=g["name"], kind="content",
                                       category="게임", volume=float(g.get("peak") or 0),
                                       url=f"https://store.steampowered.com/app/{g.get('appid')}"))
        return rerank(items)
