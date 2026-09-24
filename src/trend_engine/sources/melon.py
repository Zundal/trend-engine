"""멜론 TOP100 — 키 없는 JSON. 한국 10·20대 음악 신호 (애플 차트보다 국내 팬덤에 가깝다)."""

from __future__ import annotations

import json

from ..models import TrendItem
from .base import Source, get_text, rerank
from .signal_bz import KOREA

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
)
TOP = 50


class Melon(Source):
    name = "melon"
    label = "멜론 차트"
    kind = "content"
    weight = 0.45
    regions = KOREA

    async def fetch(self, client, region, settings):
        raw = await get_text(
            client,
            "https://www.melon.com/chart/index.json",
            headers={"User-Agent": BROWSER_UA, "Referer": "https://www.melon.com/chart/index.htm"},
        )
        songs = []
        for s in (json.loads(raw).get("songList") or [])[:TOP]:
            name = (s.get("songName") or "").strip()
            if not name:
                continue
            artist = (s.get("artistNameBasket") or "").strip()
            songs.append({
                "rank": int(s.get("curRank") or 0),
                "song": name,
                "artist": artist,
                "songId": s.get("songId"),
            })
        return json.dumps({"songs": songs}, ensure_ascii=False)

    def parse(self, raw, region):
        items = []
        for s in json.loads(raw).get("songs", []):
            name = (s.get("song") or "").strip()
            if not name:
                continue
            artist = (s.get("artist") or "").strip()
            sid = s.get("songId")
            items.append(TrendItem(
                source=self.name, region=region, rank=0, keyword=name, kind="content",
                category="음악",
                url=f"https://www.melon.com/song/detail.htm?songId={sid}" if sid else None,
                related=[artist] if artist else [],
                meta={"chart": "melon_top100", "artist": artist},
            ))
        return rerank(items)
