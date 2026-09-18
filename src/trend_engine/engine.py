"""Orchestrates: collect all sources concurrently -> cluster/score -> persist."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import fields
from datetime import timedelta

import httpx

from .config import Settings, get_region
from .models import TrendCluster, TrendItem, TrendReport
from .scoring import build_clusters
from .sources import REGISTRY, Source
from .store import Store, utcnow

log = logging.getLogger(__name__)
_CLUSTER_FIELDS = {f.name for f in fields(TrendCluster)}


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.timeout,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    )


class TrendEngine:
    def __init__(self, settings: Settings | None = None, store: Store | None = None):
        self.settings = settings or Settings.from_env()
        self.store = store if store is not None else Store(self.settings.db_path)

    def sources_for(self, region_code: str, only: list[str] | None = None) -> list[Source]:
        region = get_region(region_code)
        return [s for name, s in REGISTRY.items() if (not only or name in only) and s.supports(region)]

    def source_overview(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "label": s.label,
                "kind": s.kind,
                "weight": s.weight,
                "regions": sorted(s.regions) if s.regions else "any",
                "missing_keys": s.missing_keys(self.settings),
            }
            for s in REGISTRY.values()
        ]

    async def _run_source(self, src: Source, client, region) -> tuple[str, list[TrendItem] | Exception]:
        try:
            return src.name, await src.collect(client, region, self.settings)
        except Exception as e:  # one broken source must never break the report
            log.warning("source %s failed: %s", src.name, e)
            return src.name, e

    async def collect(self, region_code: str = "KR", only: list[str] | None = None, save: bool = True) -> TrendReport:
        region = get_region(region_code)
        sources = self.sources_for(region.code, only)
        async with make_client(self.settings) as client:
            results = await asyncio.gather(*(self._run_source(s, client, region) for s in sources))

        status: dict[str, dict] = {}
        keyword_items: list[TrendItem] = []
        content: dict[str, list[TrendItem]] = {}
        for name, res in results:
            if isinstance(res, Exception):
                status[name] = {"ok": False, "count": 0, "error": str(res)}
                continue
            status[name] = {"ok": True, "count": len(res), "error": None}
            if REGISTRY[name].kind == "content":
                content[name] = res
            else:
                keyword_items.extend(res)

        previous = None
        if save and self.store is not None:
            prev = self.store.previous_report(region.code)
            if prev:
                previous = [TrendCluster(**{k: v for k, v in c.items() if k in _CLUSTER_FIELDS}) for c in prev["clusters"]]

        weights = {name: s.weight for name, s in REGISTRY.items()}
        families = {name: s.family or name for name, s in REGISTRY.items()}
        clusters = build_clusters(keyword_items, [i for v in content.values() for i in v], weights, previous,
                                  families=families)
        report = TrendReport(
            region=region.code,
            region_name=region.name,
            generated_at=utcnow().isoformat(timespec="seconds"),
            clusters=clusters,
            content=content,
            source_status=status,
        )
        if save and self.store is not None:
            self.store.save_report(report.to_dict())
        return report

    async def report(self, region_code: str = "KR", max_age_minutes: int = 15) -> dict:
        """Cached report if fresh enough, else collect."""
        cached = self.store.latest_report(get_region(region_code).code, timedelta(minutes=max_age_minutes))
        if cached:
            return cached
        return (await self.collect(region_code)).to_dict()
