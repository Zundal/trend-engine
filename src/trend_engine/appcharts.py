"""Paid app sales rank per country and category (iPhone only). No key needed.

A chart to read on its own, not a trend signal, so it stays out of sources/ and the score. One country
is 25 requests, so calls are paced and results cached (default 6h).
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

import httpx

from .config import Settings
from .engine import make_client
from .sources.base import TransientError, get_text_retry
from .store import Store, utcnow

URL = "https://itunes.apple.com/{country}/rss/toppaidapplications/limit={limit}/{genre}json"
LIMIT = 20
PACE_SECONDS = 0.5

# The feed names a category in the country's own language, so the Korean label is fixed here.
GENRES: dict[str, str] = {
    "전체": "", "게임": "6014", "생산성": "6007", "유틸리티": "6002", "사진 및 비디오": "6008",
    "그래픽 및 디자인": "6027", "개발자 도구": "6026", "교육": "6017", "도서": "6018", "참고": "6006",
    "건강 및 피트니스": "6013", "의료": "6020", "라이프스타일": "6012", "음악": "6011", "엔터테인먼트": "6016",
    "소셜 네트워킹": "6005", "뉴스": "6009", "날씨": "6001", "여행": "6003", "내비게이션": "6010",
    "스포츠": "6004", "음식 및 음료": "6023", "쇼핑": "6024", "금융": "6015", "비즈니스": "6000",
}


def _label(entry: dict[str, Any], field: str) -> str:
    return (entry.get(field) or {}).get("label", "").strip()


def parse_chart(raw: str) -> list[dict[str, Any]]:
    """Pure: feed body -> ranked apps. A lone entry arrives as an object and an empty chart has no key."""
    entries = json.loads(raw)["feed"].get("entry", [])
    apps = []
    for rank, e in enumerate([entries] if isinstance(entries, dict) else entries, 1):
        url = _label(e, "id")
        # amount + currency, not the feed's price label: Taiwan's says "$235.00", which reads as US dollars
        price = (e.get("im:price") or {}).get("attributes", {})
        if name := _label(e, "im:name"):
            apps.append({"rank": rank, "name": name, "artist": _label(e, "im:artist"),
                         "price": float(price.get("amount", 0)), "currency": price.get("currency", ""),
                         "url": url if url.startswith("https://") else None})  # opened as-is by the page
    return apps


async def top(settings: Settings, store: Store, country: str, max_age: timedelta = timedelta(hours=6)) -> dict[str, Any]:
    if settings.offline:
        sample = json.loads((settings.fixtures_dir / "app_charts" / "sample.json").read_text(encoding="utf-8"))
        return {"generated_at": sample["generated_at"], "categories": sample["countries"].get(country, {}), "errors": []}
    key = f"app-charts:v1:{country}"
    if hit := store.cache_get(key, max_age):
        return hit

    categories: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    async with make_client(settings) as client:
        for name, genre in GENRES.items():
            url = URL.format(country=country.lower(), limit=LIMIT, genre=f"genre={genre}/" if genre else "")
            try:
                if apps := parse_chart(await get_text_retry(client, url, retries=1)):
                    categories[name] = apps
            except (TransientError, httpx.HTTPError) as e:  # blocked: waiting on the other 24 would stall the deploy
                errors.append(f"{name}: {e}")
                break
            except Exception as e:  # noqa: BLE001 — one broken feed must not hide the other categories
                errors.append(f"{name}: {e}")
            await asyncio.sleep(PACE_SECONDS)
    result = {"generated_at": utcnow().isoformat(timespec="seconds"), "categories": categories, "errors": errors}
    if not errors:
        store.cache_set(key, result)
    return result
