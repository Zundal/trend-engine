"""넷플릭스 Top10 — 공개 TSV (키 불필요). 주간 글로벌 목록만 쓴다.

나라별 all-weeks-countries.tsv 는 ~30MB 라 수집 주기마다 받기엔 무겁다.
글로벌 최신 주(영·비영어 영화/TV 각 10 = 40편)만 잘라 content 신호로 쓴다.
"""

from __future__ import annotations

import csv
import io
import json

from ..models import TrendItem
from .base import Source, SourceError, get_text, rerank

# Chrome UA 는 unsupportedbrowser 로 리다이렉트된다. 단순 UA 만 통과.
TSV_UA = "trend-engine/1.0 (+https://github.com; research)"
GLOBAL_TSV = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"

# Tudum category → 우리 택소노미 (영화·드라마 모두 연예·방송)
_CAT = {
    "Films (English)": "연예·방송",
    "Films (Non-English)": "연예·방송",
    "TV (English)": "연예·방송",
    "TV (Non-English)": "연예·방송",
}


def _latest_week_rows(tsv: str) -> tuple[str, list[dict]]:
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    rows = list(reader)
    if not rows:
        return "", []
    week = max(r["week"] for r in rows if r.get("week"))
    latest = [r for r in rows if r.get("week") == week]
    latest.sort(key=lambda r: (r.get("category") or "", int(r.get("weekly_rank") or 99)))
    return week, latest


class Netflix(Source):
    name = "netflix"
    label = "넷플릭스 Top10"
    kind = "content"
    weight = 0.35

    async def fetch(self, client, region, settings):
        raw = await get_text(client, GLOBAL_TSV, headers={"User-Agent": TSV_UA})
        if "show_title" not in raw.split("\n", 1)[0]:
            raise SourceError("netflix TSV blocked or HTML interstitial (check User-Agent)")
        week, latest = _latest_week_rows(raw)
        slim = []
        for r in latest:
            title = (r.get("show_title") or "").strip()
            if not title:
                continue
            views = r.get("weekly_views") or r.get("weekly_hours_viewed") or "0"
            try:
                volume = float(views)
            except ValueError:
                volume = 0.0
            slim.append({
                "week": week,
                "category": r.get("category") or "",
                "rank": int(r.get("weekly_rank") or 0),
                "title": title,
                "season": (r.get("season_title") or "").strip(),
                "views": volume,
            })
        return json.dumps({"week": week, "shows": slim}, ensure_ascii=False)

    def parse(self, raw, region):
        data = json.loads(raw)
        items = []
        for s in data.get("shows") or []:
            title = (s.get("title") or "").strip()
            if not title:
                continue
            tudum_cat = s.get("category") or ""
            season = (s.get("season") or "").strip()
            related = [season] if season and season != "N/A" else []
            items.append(TrendItem(
                source=self.name, region=region, rank=0, keyword=title, kind="content",
                category=_CAT.get(tudum_cat, "연예·방송"),
                volume=float(s.get("views") or 0) or None,
                related=related,
                meta={"chart": "netflix_top10", "week": data.get("week"), "tudum_category": tudum_cat},
            ))
        return rerank(items)
