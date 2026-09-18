"""Live harness: `doctor` probes every upstream, `record` refreshes tests/fixtures from live data.

Offline side of the harness lives in Settings.offline (fixtures -> Source.parse) and tests/.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .config import Settings, get_region
from .engine import make_client
from .segments import SegmentProfiler
from .seoul import SeoulCity
from .sources import REGISTRY


async def doctor(settings: Settings, region: str = "KR") -> list[dict[str, Any]]:
    reg = get_region(region)
    rows: list[dict[str, Any]] = []
    async with make_client(settings) as client:
        for src in REGISTRY.values():
            row: dict[str, Any] = {"check": src.name, "label": src.label}
            if not src.supports(reg):
                rows.append(row | {"status": "skip", "detail": f"region {reg.code} not supported"})
                continue
            if missing := src.missing_keys(settings):
                rows.append(row | {"status": "skip", "detail": f"missing {', '.join(missing)}"})
                continue
            t0 = time.perf_counter()
            try:
                items = src.parse(await src.fetch(client, reg, settings), reg.code)
                ok = len(items) > 0
                rows.append(row | {"status": "ok" if ok else "warn", "count": len(items),
                                   "ms": round((time.perf_counter() - t0) * 1000),
                                   "detail": items[0].keyword if items else "parsed 0 items (format changed?)"})
            except Exception as e:  # noqa: BLE001
                rows.append(row | {"status": "fail", "detail": str(e)[:160]})

    prof = SegmentProfiler(settings)
    if prof.available:
        try:
            r = await prof.profile(["아이폰"], [])
            rows.append({"check": "naver_datalab", "label": "네이버 DataLab", "status": "fail" if r.errors else "ok",
                         "detail": "; ".join(r.errors) or f"아이폰 = 날씨의 {r.relative['아이폰'].get('전체')}%"})
        except Exception as e:  # noqa: BLE001
            rows.append({"check": "naver_datalab", "label": "네이버 DataLab", "status": "fail", "detail": str(e)[:160]})
    else:
        rows.append({"check": "naver_datalab", "label": "네이버 DataLab", "status": "skip", "detail": "missing NAVER_CLIENT_ID/SECRET"})

    seoul = await SeoulCity(settings).hotspots(["강남역"])
    rows.append({"check": "seoul_citydata", "label": "서울 도시데이터",
                 "status": "ok" if seoul["places"] else "fail",
                 "detail": ("sample key: " if seoul["sample"] else "") + ", ".join(p["name"] for p in seoul["places"]) + " ".join(seoul["errors"])})
    rows.append({"check": "anthropic", "label": "Claude 브리핑", "status": "ok" if settings.anthropic_api_key else "skip",
                 "detail": settings.ai_model if settings.anthropic_api_key else "missing ANTHROPIC_API_KEY"})
    return rows


async def record(settings: Settings, regions: list[str]) -> list[str]:
    """Overwrite fixtures with live responses. Review the diff before committing!"""
    written: list[str] = []
    done: set[tuple[str, str]] = set()
    async with make_client(settings) as client:
        for code in regions:
            reg = get_region(code)
            for src in REGISTRY.values():
                target = (src.name, src.fixture_code(reg))
                if not src.supports(reg) or src.missing_keys(settings) or target in done:
                    continue
                done.add(target)
                try:
                    raw = await src.fetch(client, reg, settings)
                    if not src.parse(raw, reg.code):
                        written.append(f"SKIP {src.name}/{reg.code}: parsed 0 items")
                        continue
                except Exception as e:  # noqa: BLE001
                    written.append(f"FAIL {src.name}/{reg.code}: {e}")
                    continue
                path = settings.fixtures_dir / src.name / f"{src.fixture_code(reg)}.{src.fixture_ext}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(raw, encoding="utf-8")
                written.append(f"OK   {path.relative_to(settings.fixtures_dir.parent.parent)}")
    return written


def run(coro):
    return asyncio.run(coro)
