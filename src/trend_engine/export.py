"""Static site export for GitHub Pages: bake every API response into site/api/*.json.

The dashboard (web/index.html) detects static mode via meta.json {"static": true} and reads
these files instead of calling the live API. Run by .github/workflows/pages.yml on a schedule.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from .service import TrendService

log = logging.getLogger(__name__)
WEB = Path(__file__).parent / "web"
# Search Trend quota (NAVER API HUB ~50k calls/month): ~36 calls per region per refresh, so segments
# are recomputed at most every 3h per region even though the site deploys hourly.
SEGMENT_REFRESH = timedelta(hours=3)


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


async def export_site(svc: TrendService, out: Path, regions: list[str], brief_regions: list[str]) -> list[str]:
    api = out / "api"
    lines: list[str] = []
    out.mkdir(parents=True, exist_ok=True)
    page = (WEB / "index.html").read_text(encoding="utf-8")
    marker = "let STATIC = false;"
    assert marker in page, "index.html static-mode marker missing"
    (out / "index.html").write_text(page.replace(marker, "let STATIC = true;", 1), encoding="utf-8")
    (out / ".nojekyll").write_text("")

    meta = svc.meta() | {"static": True}
    meta["regions"] = [r for r in meta["regions"] if r["code"] in regions]
    meta["features"]["keyword_lookup"] = False

    for code in regions:
        report = (await svc.engine.collect(code)).to_dict()
        _write(api / f"report-{code}.json", report)
        ok = sum(1 for s in report["source_status"].values() if s["ok"])
        lines.append(f"report {code}: {len(report['clusters'])} clusters, {ok}/{len(report['source_status'])} sources ok")

        history = {c["key"]: [{"generated_at": h["generated_at"], "rank": h["rank"]} for h in svc.history(code, c["key"])]
                   for c in report["clusters"]}
        _write(api / f"history-{code}.json", history)

        # Naver search data only describes Korean users — skip foreign regions (saves quota).
        if meta["features"]["segments"] and code.startswith("KR"):
            try:
                seg = svc.store.cache_get(f"segments-latest:{code}", SEGMENT_REFRESH)
                if seg is None:
                    seg = await svc.report_segments(code)
                    svc.store.cache_set(f"segments-latest:{code}", seg)
                    lines.append(f"segments {code}: refreshed")
                else:
                    lines.append(f"segments {code}: reused (<3h)")
                _write(api / f"segments-{code}.json", seg)
            except Exception as e:  # noqa: BLE001 — a failed extra must not fail the deploy
                _write(api / f"segments-{code}.json", {"error": f"연령·성별 데이터 오류: {e}"})
                lines.append(f"segments {code}: FAIL {e}")

        if code in brief_regions and meta["features"]["ai"]:
            try:
                _write(api / f"brief-{code}.json", await svc.brief(code))
                lines.append(f"brief {code}: ok")
            except Exception as e:  # noqa: BLE001
                lines.append(f"brief {code}: FAIL {e}")
        meta.setdefault("briefs", [])
        if (api / f"brief-{code}.json").exists():
            meta["briefs"].append(code)

    _write(api / "seoul.json", await svc.seoul())
    try:
        shop = await svc.shopping()  # cached 3h inside ShoppingInsight
        _write(api / "shopping.json", shop)
        lines.append(f"shopping: {len(shop['by_segment'])} segments, {len(shop['errors'])} errors")
    except Exception as e:  # noqa: BLE001
        lines.append(f"shopping: FAIL {e}")
    _write(api / "meta.json", meta)
    lines.append(f"wrote {out}")
    return lines
