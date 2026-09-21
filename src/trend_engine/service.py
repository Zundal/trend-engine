"""Application service: the one façade the API and CLI share (so they can't drift apart)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import alerts as alerts_mod
from . import archive, diffusion, entities, flux, kernel, pageviews, pomdp, youth
from . import shapes as shapes_mod
from .config import REGIONS, Settings, get_region
from .engine import TrendEngine
from .segments import AGE_GROUPS, DEFAULT_SEGMENTS, GENDERS, OLDER, YOUTH_GROUPS, SegmentProfiler, parse_segment
from .shopping import ShoppingInsight
from .store import Store

ENTITY_BUDGET = 400  # uncached pageview requests one 국가 간 전파 pass may make
DAY_BUDGET = 150  # uncached day-lists one 교체율 pass may fetch (~30s); the rest fills in next run
RECENT_DAYS = 90  # 유행의 모양: only peaks recent enough to still be "요즘"
SLOW_RISE = 120  # ... and a rise longer than this is an evergreen drift, not a burst
WATCH_LIMIT = 50  # tracked keywords per diffusion run (≈ 75 paced search-data requests)
WATCH_SPARE = 20  # extra candidates for pomdp.plan to pick from when settled keywords rest

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
        if hit := self.store.cache_get("diffusion:v10", max_age):
            return hit
        y = await self.youth()
        report = await self.report("KR")
        today = archive.kst_today()
        watchlist = alerts_mod.load_watchlist(Path(self.settings.watchlist_path))
        candidates = diffusion.tracked_keywords(y["discover"], self.youth_period()["month"], report=report,
                                                pinned=watchlist, limit=WATCH_LIMIT + WATCH_SPARE)
        keywords = self.watch_list(candidates, watchlist, today=today)
        cases = self.store.cache_get("diffusion-cases:v2", timedelta(days=30))
        if cases is None:
            cases = await diffusion.cases(self.settings, self.store)
            self.store.cache_set("diffusion-cases:v2", cases)
        # the phase model learns from this run's backtest *and* every archived day so far
        history = archive.diffusion_sequences(self.store, self.archive_root, today=today)
        tracked = await diffusion.track(self.settings, self.store, keywords, typical_lag=diffusion.typical_lags(cases),
                                        extra_sequences=history)
        self.store.cache_set("pomdp-model:v1", tracked["model"])
        known = {r["keyword"]: r.get("category") for rows in y["discover"]["groups"].values() for r in rows}
        for it in tracked["items"]:
            it["category"] = known.get(it["keyword"]) or "기타"
        self._observe(tracked, today)
        # raw weekly series are the kernel's input: keep them, but out of the published payload
        weeklies = {"tracked": tracked.pop("weeklies", {}),
                    "cases": {c["keyword"]: c.pop("weeklies", {}) for c in cases.get("items", [])},
                    "stages": {i["keyword"]: i["stage"] for i in tracked["items"]},
                    "case_stages": {c["keyword"]: c.get("stage") for c in cases.get("items", [])}}
        self.store.cache_set("age-weeklies:v1", weeklies)
        result = {"tracked": tracked, "cases": cases, "watchlist": watchlist}
        self.store.cache_set("diffusion:v10", result)
        archive.record_daily(self.store, archive.kst_today(), "diffusion", {
            "stages": {i["keyword"]: {"stage": i["stage"], "old_lag_weeks": i["old_lag_weeks"]} for i in tracked["items"]}})
        return result

    # --- POMDP: the belief over each keyword's phase lives across runs (pomdp.py, docs/POMDP.md)
    def beliefs(self) -> dict[str, pomdp.Belief]:
        raw = self.store.cache_get("belief:v1", timedelta(days=60)) or {}
        return {k: pomdp.Belief.from_dict(v) for k, v in raw.items()}

    def watch_list(self, candidates: list[str], pinned: list[str], limit: int = WATCH_LIMIT,
                   today: date | None = None) -> list[str]:
        """The measurement action: which keywords get search-data requests this run."""
        return pomdp.plan(self.beliefs(), candidates, pinned, limit, today or archive.kst_today())

    def _observe(self, tracked: dict[str, Any], today: date) -> None:
        """Bayes step per tracked keyword with today's verdict; one observation per day at most."""
        model = pomdp.Model.from_dict(tracked.get("model"))
        beliefs = self.beliefs()
        for it in tracked["items"]:
            b = beliefs.get(it["keyword"]) or pomdp.Belief.initial()
            days = b.days_since(today)
            if days is None:
                b = b.update(it["stage"], pomdp.WEEK, model)
            elif days > 0:
                b = b.update(it["stage"], days, model)
            beliefs[it["keyword"]] = b = b.stamp(today)
            it["belief"] = b.to_dict()
        keep = {k: b.to_dict() for k, b in beliefs.items() if (b.days_since(today) or 0) <= 60}
        self.store.cache_set("belief:v1", keep)

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

    async def transfer(self, max_age: timedelta = timedelta(days=3)) -> dict[str, Any] | None:
        """세대 전달 함수: the shape of the handover from 20대 to each older age, estimated over many
        keywords at once (kernel.py). Two populations are fitted separately because they answer
        different questions — trends that actually spread, and everything else."""
        if (hit := self.store.cache_get("transfer:v1", max_age)) is not None:
            return hit
        data = self.store.cache_get("age-weeklies:v1", timedelta(days=2))
        if data is None:
            return None  # written by the next diffusion refresh; not worth forcing a DataLab run here
        groups = kernel.split_populations(data)
        out: dict[str, Any] = {"groups": {}, "ages": kernel.OLDER_AGES, "young": kernel.YOUNG_AGE}
        for name, pairs_by_age in groups.items():
            names = sorted(pairs_by_age.pop("_names", []))
            fitted = {age: kernel.fit(pairs) for age, pairs in pairs_by_age.items() if pairs}
            rows = {age: k.to_dict() for age, k in fitted.items() if k}
            if rows and len(names) >= kernel.MIN_KEYWORDS:
                middle = pairs_by_age.get("40대") or next(iter(pairs_by_age.values()))
                out["groups"][name] = {"ages": rows, "keywords": names[:40], "n_keywords": len(names),
                                       "stability": kernel.jackknife(middle)}
        if not out["groups"]:
            return None
        out["contrast"] = kernel.contrast(out["groups"])
        self.store.cache_set("transfer:v1", out)
        return out

    async def crosscountry(self, langs: tuple[str, ...] = ("ko", "ja", "en"), per_day: int = 30,
                           max_age: timedelta = timedelta(days=7)) -> dict[str, Any] | None:
        """국가 간 전파: the same entity, read in several languages, run through the transfer kernel.

        Entities are joined through Wikidata (entities.py) and tagged with the country whose list
        they first showed up in, because the tag is what turns "Korea leads everything" (an artefact
        of which topics we sampled) into "a topic leads from where it came from" (a measurement).
        """
        if (hit := self.store.cache_get("crosscountry:v1", max_age)) is not None:
            return hit
        origin: dict[str, str] = {}
        links: dict[str, dict[str, str]] = {}
        async with pageviews.History(self.settings, self.store, budget=ENTITY_BUDGET) as hist, \
                entities.Entities(self.settings, self.store) as ent:
            end = min(hist.latest_day(lang) for lang in langs)  # offline: whatever the fixture holds
            start = end - timedelta(days=420)
            for lang in langs:
                titles: list[str] = []
                for back in (2, 30, 60, 120, 200):
                    titles += [a for a, _ in await hist.top(lang, end - timedelta(days=back), limit=per_day)]
                found = await ent.align(list(dict.fromkeys(titles)), lang, list(langs))
                for qid, sitelinks in found.items():
                    links[qid] = sitelinks
                    origin.setdefault(qid, lang)  # first list it appeared in
            series: dict[str, dict[str, list[float]]] = {l: {} for l in langs}
            for qid, sitelinks in links.items():
                for lang in langs:
                    title = sitelinks.get(lang)
                    if not title:
                        continue
                    rows = await hist.article(lang, title, start, end)
                    weeks = kernel.weekly_counts(rows) if rows else []
                    if len(weeks) >= 30 and max(weeks) > 200:
                        series[lang][qid] = kernel.normalise(weeks)
            skipped = hist.skipped
        # offline replays a handful of recorded entities; the production floor would reject them
        flows = kernel.country_flows(series, origin, min_entities=3 if self.settings.offline else 8)
        if not flows:
            return None
        result = {"langs": list(langs), "entities": len(links), "flows": flows,
                  "measured": {l: len(v) for l, v in series.items()}, "filling": skipped}
        self.store.cache_set("crosscountry:v1", result)
        return result

    async def attention(self, region: str = "KR", days: int = 400,
                        max_age: timedelta = timedelta(hours=12)) -> dict[str, Any] | None:
        """교체율·쏠림 (나라별). Reads past most-read lists, which go back years — unlike our own
        archive, so this works from day one and for countries with no age data."""
        lang = get_region(region).lang
        key = f"attention:v2:{lang}:{days}"
        if (hit := self.store.cache_get(key, max_age)) is not None:
            return hit
        async with pageviews.History(self.settings, self.store, budget=DAY_BUDGET) as hist:
            # newest first: a capped run always has the recent days, and reaches further back each time
            wanted = pageviews.days_back(days, hist.latest_day(lang) + timedelta(days=1))
            by_day = await hist.top_days(lang, list(reversed(wanted)))
            skipped = hist.skipped
        rows = flux.daily(by_day)
        summary = flux.summary(rows)
        if summary is None:
            return None
        result = {"region": region, "days": len(rows), "summary": summary, "trend": flux.trend(rows),
                  "filling": skipped}  # > 0 = still working back through the history
        self.store.cache_set(key, result)
        return result

    async def shapes(self, region: str = "KR", top: int = 40,
                     max_age: timedelta = timedelta(hours=12)) -> dict[str, Any] | None:
        """유행의 모양 (나라별): how each of today's risers got its attention. A shape can only be
        read a week after the peak — fresher items are left unlabelled rather than guessed."""
        lang = get_region(region).lang
        key = f"shapes:v2:{lang}:{top}"
        if (hit := self.store.cache_get(key, max_age)) is not None:
            return hit
        async with pageviews.History(self.settings, self.store, budget=top + 10) as hist:
            end = hist.latest_day(lang)
            rows = await hist.top(lang, end, limit=top)
            series = await hist.articles(lang, [a for a, _ in rows], end - timedelta(days=540), end)
            errors = list(hist.errors)
        items = []
        for name, s in series.items():
            shaped = [x for x in ((b, shapes_mod.shape_of(s, b)) for b in shapes_mod.bursts(s)) if x[1]]
            if not shaped:
                continue
            burst, shape = shaped[-1]  # the most recent burst we can actually read
            since = (end - burst.peak).days
            if since > RECENT_DAYS or burst.rise_days > SLOW_RISE:
                continue  # old news, or a slow evergreen drift rather than a burst
            items.append({"label": name.replace("_", " ")} | shape
                         | {"days_since_peak": since, "recurring": shapes_mod.recurs(s, burst)})
        items.sort(key=lambda i: i["days_since_peak"])
        mix: dict[str, int] = {}
        for i in items:
            mix[i["shape"]] = mix.get(i["shape"], 0) + 1
        result = {"region": region, "day": end.isoformat(), "items": items[:12], "mix": mix,
                  "classes": shapes_mod.CLASSES, "errors": errors[:3]}
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
