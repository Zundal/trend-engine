"""YouTube Data API v3 'mostPopular' chart per country. Needs YOUTUBE_API_KEY. Content source."""

from __future__ import annotations

import json

from ..models import TrendItem
from .base import Source, get_text, rerank

# Stable YouTube video category ids -> Korean label.
CATEGORIES = {
    "1": "영화/애니", "2": "자동차", "10": "음악", "15": "동물", "17": "스포츠", "19": "여행",
    "20": "게임", "22": "인물/블로그", "23": "코미디", "24": "엔터테인먼트", "25": "뉴스/정치",
    "26": "노하우/스타일", "27": "교육", "28": "과학기술", "29": "비영리",
}


class YouTube(Source):
    name = "youtube"
    label = "YouTube 인기"
    kind = "content"
    weight = 0.6
    requires = ("youtube_api_key",)

    async def fetch(self, client, region, settings):
        return await get_text(
            client,
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": region.country,
                "maxResults": 50,
                "key": settings.youtube_api_key,
            },
        )

    def parse(self, raw, region):
        data = json.loads(raw)
        items = []
        for v in data.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            title = (sn.get("title") or "").strip()
            if not title:
                continue
            items.append(
                TrendItem(
                    source=self.name,
                    region=region,
                    rank=0,
                    keyword=title,
                    kind="content",
                    volume=float(st.get("viewCount", 0) or 0),
                    url=f"https://www.youtube.com/watch?v={v.get('id')}",
                    category=CATEGORIES.get(str(sn.get("categoryId")), None),
                    related=list(sn.get("tags", []) or [])[:10],
                    meta={
                        "channel": sn.get("channelTitle"),
                        "published_at": sn.get("publishedAt"),
                        "likes": int(st.get("likeCount", 0) or 0),
                        "comments": int(st.get("commentCount", 0) or 0),
                        "thumbnail": (sn.get("thumbnails", {}).get("medium") or {}).get("url"),
                    },
                )
            )
        return rerank(items)
