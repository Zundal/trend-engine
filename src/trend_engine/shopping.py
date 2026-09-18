"""Naver Shopping Insight: top shopping searches per category, per age / gender. No key needed.

Answers "20대 여성은 요즘 뭘 찾나" directly (discovery, unlike DataLab search trend which only profiles
keywords we already have). Uses the public datalab.naver.com endpoint — unofficial, so calls are paced
and results cached (default 3h).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from .config import Settings
from .store import Store

log = logging.getLogger(__name__)

URL = "https://datalab.naver.com/shoppingInsight/getCategoryKeywordRank.naver"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
PACE_SECONDS = 1.0

CATEGORIES: dict[str, str] = {
    "패션의류": "50000000", "패션잡화": "50000001", "화장품/미용": "50000002", "디지털/가전": "50000003",
    "가구/인테리어": "50000004", "출산/육아": "50000005", "식품": "50000006", "스포츠/레저": "50000007",
    "생활/건강": "50000008", "여가/생활편의": "50000009", "도서": "50005542",
}
# Shopping Insight age values are decades ("10".."60"); gender "f" / "m".
SEGMENTS: dict[str, dict[str, str]] = {
    "10대": {"age": "10"}, "20대": {"age": "20"}, "30대": {"age": "30"}, "40대": {"age": "40"},
    "50대": {"age": "50"}, "60대+": {"age": "60"}, "남성": {"gender": "m"}, "여성": {"gender": "f"},
    "20대 여성": {"age": "20", "gender": "f"}, "20대 남성": {"age": "20", "gender": "m"},
}


def parse_rank(raw: str) -> list[str]:
    data = json.loads(raw)
    if data.get("returnCode") not in (0, None):
        raise RuntimeError(f"shopping insight returnCode={data.get('returnCode')} {data.get('message')}")
    return [r["keyword"] for r in sorted(data.get("ranks", []), key=lambda r: r["rank"]) if r.get("keyword")]


def distinctive(segment: list[str], overall: list[str]) -> list[str]:
    """Keywords in the segment's top list that the overall top list doesn't have — '이 그룹만의 관심'."""
    base = set(overall)
    return [k for k in segment if k not in base]


class ShoppingInsight:
    def __init__(self, settings: Settings, store: Store | None = None):
        self.settings, self.store = settings, store

    async def _rank(self, client: httpx.AsyncClient, cid: str, filters: dict[str, str], start: str, end: str,
                    count: int) -> list[str]:
        form = {"cid": cid, "timeUnit": "date", "startDate": start, "endDate": end, "age": filters.get("age", ""),
                "gender": filters.get("gender", ""), "device": "", "page": "1", "count": str(count)}
        for attempt in range(4):
            r = await client.post(URL, data=form, headers={
                "User-Agent": UA, "Referer": "https://datalab.naver.com/shoppingInsight/sCategory.naver"})
            if r.status_code == 200 and r.text.strip().startswith("{"):
                await asyncio.sleep(PACE_SECONDS)
                return parse_rank(r.text)
            await asyncio.sleep(float(r.headers.get("Retry-After") or 10 * 2**attempt))
        raise RuntimeError(f"shopping insight HTTP {r.status_code}")

    async def top(self, segments: list[str] | None = None, categories: list[str] | None = None,
                  count: int = 10, max_age: timedelta = timedelta(hours=3), days: int = 7) -> dict[str, Any]:
        """Top shopping searches over the last `days` days (7 = 이번 주, 30 = 이번 달)."""
        segments = segments or list(SEGMENTS)
        categories = categories or list(CATEGORIES)
        cache_key = f"shopping:{days}d:{','.join(segments)}:{','.join(categories)}:{count}"
        if self.store and (hit := self.store.cache_get(cache_key, max_age)):
            return hit
        if self.settings.offline:
            raw = (self.settings.fixtures_dir / "shopping_insight" / "sample.json").read_text(encoding="utf-8")
            return json.loads(raw) | {"synthetic": False, "offline": True}

        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=days - 1)
        s, e = start.isoformat(), end.isoformat()
        overall: dict[str, list[str]] = {}
        by_seg: dict[str, dict[str, dict[str, list[str]]]] = {}
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
            for cat in categories:
                try:
                    overall[cat] = await self._rank(client, CATEGORIES[cat], {}, s, e, count)
                except Exception as ex:  # noqa: BLE001
                    errors.append(f"{cat}: {ex}")
                    overall[cat] = []
            for seg in segments:
                by_seg[seg] = {}
                for cat in categories:
                    try:
                        top = await self._rank(client, CATEGORIES[cat], SEGMENTS[seg], s, e, count)
                    except Exception as ex:  # noqa: BLE001
                        errors.append(f"{seg}/{cat}: {ex}")
                        continue
                    by_seg[seg][cat] = {"top": top, "distinctive": distinctive(top, overall.get(cat, []))}
        result = {"period": [s, e], "categories": categories, "segments": segments, "overall": overall,
                  "by_segment": by_seg, "errors": errors}
        if self.store and not errors:
            self.store.cache_set(cache_key, result)
        return result
