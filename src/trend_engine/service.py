"""Application service: the one façade the API and CLI share (so they can't drift apart)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pathlib import Path

from . import ai, archive
from .config import REGIONS, Settings, get_region
from .engine import TrendEngine
from .seoul import SeoulCity
from .shopping import ShoppingInsight
from .segments import AGE_GROUPS, DEFAULT_SEGMENTS, GENDERS, SegmentProfiler, parse_segment
from .store import Store


class TrendService:
    def __init__(self, settings: Settings | None = None, store: Store | None = None):
        self.settings = settings or Settings.from_env()
        self.store = store if store is not None else Store(self.settings.db_path)
        self.engine = TrendEngine(self.settings, self.store)
        self.seoul_city = SeoulCity(self.settings, self.store)
        self.shopping_insight = ShoppingInsight(self.settings, self.store)

    def meta(self) -> dict[str, Any]:
        s = self.settings
        return {
            "offline": s.offline,
            "regions": [{"code": r.code, "name": r.name} for r in REGIONS.values()],
            "sources": self.engine.source_overview(),
            "segments": {"default": [x.name for x in DEFAULT_SEGMENTS], "ages": list(AGE_GROUPS), "genders": list(GENDERS)},
            "features": {
                "segments": True,
                "segments_mode": "offline" if s.offline else s.naver_mode,
                "youtube": bool(s.offline or s.youtube_api_key),
                "seoul": True,
                "shopping": True,
                "seoul_full": bool(s.seoul_api_key),
                "ai": bool(s.anthropic_api_key),
            },
        }

    async def report(self, region: str = "KR", refresh: bool = False) -> dict[str, Any]:
        if refresh:
            return (await self.engine.collect(region)).to_dict()
        return await self.engine.report(region)

    def _segments(self, names: list[str] | None):
        return [parse_segment(n) for n in names] if names else DEFAULT_SEGMENTS

    async def keyword_segments(self, keywords: list[str], segments: list[str] | None = None) -> dict[str, Any]:
        profiler = SegmentProfiler(self.settings, self.store)
        if not profiler.available:
            raise PermissionError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 필요합니다 (docs/SOURCES.md)")
        return (await profiler.profile(keywords, self._segments(segments))).to_dict()

    async def report_segments(self, region: str = "KR", top: int = 16, segments: list[str] | None = None) -> dict[str, Any]:
        report = await self.report(region)
        segs = segments or [x.name for x in DEFAULT_SEGMENTS]
        key = f"segments:{report['region']}:{report['generated_at']}:{top}:{','.join(segs)}"
        if hit := self.store.cache_get(key, timedelta(hours=6)):
            return hit
        queries = [c["query"] for c in report["clusters"][:top]]
        result = await self.keyword_segments(queries, segs)
        result["labels"] = {c["query"]: c["label"] for c in report["clusters"][:top]}
        self.store.cache_set(key, result)
        return result

    async def shopping(self, segments: list[str] | None = None, categories: list[str] | None = None,
                       days: int = 7) -> dict[str, Any]:
        max_age = timedelta(hours=3) if days <= 7 else timedelta(hours=24)
        return await self.shopping_insight.top(segments, categories, max_age=max_age, days=days)

    @property
    def archive_root(self) -> Path:
        return Path(self.settings.archive_dir)

    def period(self, region: str) -> dict[str, Any]:
        code = get_region(region).code
        return {name: archive.period_trends(self.store, self.archive_root, code, n) for name, n in archive.PERIODS.items()}

    def age_period(self) -> dict[str, Any]:
        return {name: archive.period_segments(self.store, self.archive_root, n) for name, n in archive.PERIODS.items()}

    async def seoul(self, places: list[str] | None = None) -> dict[str, Any]:
        return await self.seoul_city.hotspots(places)

    async def brief(self, region: str = "KR", llm: ai.LLM | None = None) -> dict[str, Any]:
        report = await self.report(region)
        key = f"brief:{report['region']}:{report['generated_at']}"
        if llm is None and (hit := self.store.cache_get(key, timedelta(hours=6))):
            return hit
        if llm is None:
            if not self.settings.anthropic_api_key:
                raise PermissionError("ANTHROPIC_API_KEY 가 필요합니다 (pip install 'trend-engine[ai]')")
            llm = ai.claude_llm(self.settings.anthropic_api_key, self.settings.ai_model)
        segments = None
        try:
            segments = await self.report_segments(region)
        except PermissionError:
            pass
        seoul = await self.seoul() if get_region(region).code == "KR-11" else None
        result = ai.make_brief(report, llm, segments, seoul)
        self.store.cache_set(key, result)
        return result

    def history(self, region: str, key: str) -> list[dict[str, Any]]:
        return self.store.history(key, get_region(region).code)
