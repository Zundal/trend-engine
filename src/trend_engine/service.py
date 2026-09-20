"""Application service: the one façade the API and CLI share (so they can't drift apart)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from . import alerts as alerts_mod
from . import archive, diffusion, flux, pageviews, youth
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
        from . import categories as cat_mod

        max_age = timedelta(hours=3) if days <= 7 else timedelta(hours=24)
        result = await self.shopping_insight.top(segments, categories, max_age=max_age, days=days)
        if days == 7 and not segments and not categories:  # keyword -> 쇼핑 분야, used by the category classifier
            self.store.cache_set("shopping-index", cat_mod.shopping_index(result))
        return result

    async def youth(self, max_age: timedelta = timedelta(hours=3)) -> dict[str, Any]:
        """10·20대 focus view (Korea): discovered youth interests + today's issues vs 30대 이상."""
        if hit := self.store.cache_get("youth-latest:v3", max_age):
            return hit
        report = await self.report("KR")
        shopping = await self.shopping(days=7)
        segments = await self.report_segments("KR")
        result = {"discover": await youth.discover(self.settings, self.store, report, shopping),
                  "issues": youth.issue_view(segments, report)}
        self.store.cache_set("youth-latest:v3", result)
        archive.record_daily_extras(self.store, archive.kst_today(), None, None, result["discover"])
        return result

    async def diffusion(self, max_age: timedelta = timedelta(hours=20)) -> dict[str, Any]:
        """세대 확산 감지 (Korea): stage of each youth interest + validated past cases."""
        if hit := self.store.cache_get("diffusion:v7", max_age):
            return hit
        y = await self.youth()
        report = await self.report("KR")
        watchlist = alerts_mod.load_watchlist(Path(self.settings.watchlist_path))
        keywords = diffusion.tracked_keywords(y["discover"], self.youth_period()["month"], report=report,
                                              pinned=watchlist)
        cases = self.store.cache_get("diffusion-cases:v1", timedelta(days=30))
        if cases is None:
            cases = await diffusion.cases(self.settings, self.store)
            self.store.cache_set("diffusion-cases:v1", cases)
        tracked = await diffusion.track(self.settings, self.store, keywords, typical_lag=diffusion.typical_lags(cases))
        known = {r["keyword"]: r.get("category") for rows in y["discover"]["groups"].values() for r in rows}
        for it in tracked["items"]:
            it["category"] = known.get(it["keyword"]) or "기타"
        result = {"tracked": tracked, "cases": cases, "watchlist": watchlist}
        self.store.cache_set("diffusion:v7", result)
        archive.record_daily(self.store, archive.kst_today(), "diffusion", {
            "stages": {i["keyword"]: {"stage": i["stage"], "old_lag_weeks": i["old_lag_weeks"]} for i in tracked["items"]}})
        return result

    async def alerts(self, dif: dict[str, Any] | None = None) -> dict[str, Any]:
        """New alerts vs the previous run + the last two weeks of them (for the feed and the card)."""
        dif = dif or await self.diffusion()
        y = await self.youth()
        today = archive.kst_today().isoformat()
        state = self.store.cache_get("alerts-state", timedelta(days=30))
        new, next_state = alerts_mod.evaluate(dif["tracked"], y["discover"], state,
                                              dif.get("watchlist", []), today)
        history = self.store.cache_get("alerts-history", timedelta(days=60)) or []
        merged = alerts_mod.merge_recent(new, history)
        self.store.cache_set("alerts-state", next_state)
        self.store.cache_set("alerts-history", merged)
        archive.record_daily(self.store, archive.kst_today(), "alerts", {"alerts": [a.to_dict() for a in new]})
        if new and self.settings.slack_webhook:
            import httpx

            async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
                await alerts_mod.notify_slack(self.settings.slack_webhook, new, self.settings.site_url, client)
        return {"new": [a.to_dict() for a in new], "recent": merged, "watchlist": dif.get("watchlist", [])}

    async def attention(self, region: str = "KR", days: int = 400,
                        max_age: timedelta = timedelta(hours=12)) -> dict[str, Any] | None:
        """교체율·쏠림 (나라별). Reads past most-read lists, which go back years — unlike our own
        archive, so this works from day one and for countries with no age data."""
        lang = get_region(region).lang
        key = f"attention:v1:{lang}:{days}"
        if (hit := self.store.cache_get(key, max_age)) is not None:
            return hit
        async with pageviews.History(self.settings, self.store) as hist:
            by_day = await hist.top_days(lang, pageviews.days_back(days))
        rows = flux.daily(by_day)
        summary = flux.summary(rows)
        if summary is None:
            return None
        result = {"region": region, "days": len(rows), "summary": summary, "trend": flux.trend(rows)}
        self.store.cache_set(key, result)
        return result

    def youth_trend(self, days: int = 30) -> dict[str, Any]:
        """Category mix of each youth group over time (needs daily youth snapshots to accumulate)."""
        return archive.category_shares(self.store, self.archive_root, days)

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
