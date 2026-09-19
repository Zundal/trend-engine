"""Application service: the one façade the API and CLI share (so they can't drift apart)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from . import archive, diffusion, youth
from .config import REGIONS, Settings, get_region
from .engine import TrendEngine
from .segments import AGE_GROUPS, DEFAULT_SEGMENTS, GENDERS, OLDER, YOUTH_GROUPS, SegmentProfiler, parse_segment
from .shopping import ShoppingInsight
from .store import Store

# Today's-issue profiling covers every age plus the 10·20대 splits and the 30대+ baseline.
REPORT_SEGMENTS = [x.name for x in DEFAULT_SEGMENTS] + [g for g in YOUTH_GROUPS if g not in AGE_GROUPS] + [OLDER]


class TrendService:
    def __init__(self, settings: Settings | None = None, store: Store | None = None):
        self.settings = settings or Settings.from_env()
        self.store = store if store is not None else Store(self.settings.db_path)
        self.engine = TrendEngine(self.settings, self.store)
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
                "shopping": True,
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
        segs = segments or REPORT_SEGMENTS
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

    async def youth(self, max_age: timedelta = timedelta(hours=3)) -> dict[str, Any]:
        """10·20대 focus view (Korea): discovered youth interests + today's issues vs 30대 이상."""
        if hit := self.store.cache_get("youth-latest:v2", max_age):
            return hit
        report = await self.report("KR")
        shopping = await self.shopping(days=7)
        segments = await self.report_segments("KR")
        result = {"discover": await youth.discover(self.settings, self.store, report, shopping),
                  "issues": youth.issue_view(segments)}
        self.store.cache_set("youth-latest:v2", result)
        archive.record_daily_extras(self.store, archive.kst_today(), None, None, result["discover"])
        return result

    async def diffusion(self, max_age: timedelta = timedelta(hours=20)) -> dict[str, Any]:
        """세대 확산 감지 (Korea): stage of each youth interest + validated past cases."""
        if hit := self.store.cache_get("diffusion:v2", max_age):
            return hit
        y = await self.youth()
        keywords = diffusion.tracked_keywords(y["discover"], self.youth_period()["month"])
        tracked = await diffusion.track(self.settings, self.store, keywords)
        cases = self.store.cache_get("diffusion-cases:v1", timedelta(days=30))
        if cases is None:
            cases = await diffusion.cases(self.settings, self.store)
            self.store.cache_set("diffusion-cases:v1", cases)
        result = {"tracked": tracked, "cases": cases}
        self.store.cache_set("diffusion:v2", result)
        archive.record_daily(self.store, archive.kst_today(), "diffusion", {
            "stages": {i["keyword"]: {"stage": i["stage"], "old_lag_weeks": i["old_lag_weeks"]} for i in tracked["items"]}})
        return result

    def youth_period(self) -> dict[str, Any]:
        return {name: archive.period_segments(self.store, self.archive_root, n, kind="youth", top_n=8, limit=15)
                for name, n in archive.PERIODS.items()}

    @property
    def archive_root(self) -> Path:
        return Path(self.settings.archive_dir)

    def period(self, region: str) -> dict[str, Any]:
        code = get_region(region).code
        return {name: archive.period_trends(self.store, self.archive_root, code, n) for name, n in archive.PERIODS.items()}

    def age_period(self) -> dict[str, Any]:
        return {name: archive.period_segments(self.store, self.archive_root, n) for name, n in archive.PERIODS.items()}

    def history(self, region: str, key: str) -> list[dict[str, Any]]:
        return self.store.history(key, get_region(region).code)
