"""Static site export for GitHub Pages.

Every file under site/api/ is a source-neutral public view (publish.py) encrypted with
AES-256-GCM (`<name>.dat`). The built index.html gets `STATIC = true` and the data key
injected, and decrypts in the browser. Run by .github/workflows/pages.yml on a schedule.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from . import publish
from .service import TrendService

log = logging.getLogger(__name__)
WEB = Path(__file__).parent / "web"
# Search Trend quota: ~36 calls per region per refresh, so segments are recomputed at most
# every 3h per region even though the site deploys hourly.
SEGMENT_REFRESH = timedelta(hours=3)
STATIC_MARKER = "let STATIC = false;"
KEY_MARKER = 'const DATA_KEY = "";'


def build_page(key: bytes) -> str:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    for marker in (STATIC_MARKER, KEY_MARKER):
        assert marker in page, f"index.html marker missing: {marker}"
    return page.replace(STATIC_MARKER, "let STATIC = true;", 1).replace(KEY_MARKER, f'const DATA_KEY = "{key.hex()}";', 1)


async def export_site(svc: TrendService, out: Path, regions: list[str]) -> list[str]:
    key = publish.data_key()
    api = out / "api"
    api.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def write(name: str, data: Any) -> None:
        (api / f"{name}.dat").write_text(publish.encrypt(data, key), encoding="ascii")

    (out / "index.html").write_text(build_page(key), encoding="utf-8")
    (out / ".nojekyll").write_text("")

    meta = svc.meta() | {"static": True}
    meta["regions"] = [r for r in meta["regions"] if r["code"] in regions]

    for code in regions:
        report = (await svc.engine.collect(code)).to_dict()
        write(f"report-{code}", publish.public_report(report))
        ok = sum(1 for s in report["source_status"].values() if s["ok"])
        lines.append(f"report {code}: {len(report['clusters'])} clusters, {ok}/{len(report['source_status'])} ok")

        history = {c["key"]: [{"generated_at": h["generated_at"], "rank": h["rank"]} for h in svc.history(code, c["key"])]
                   for c in report["clusters"]}
        write(f"history-{code}", history)

        # Korean search data only describes Korean users — skip foreign regions (saves quota).
        if code.startswith("KR"):
            try:
                seg = svc.store.cache_get(f"segments-latest:{code}", SEGMENT_REFRESH)
                if seg is None:
                    seg = await svc.report_segments(code)
                    svc.store.cache_set(f"segments-latest:{code}", seg)
                    lines.append(f"segments {code}: refreshed")
                else:
                    lines.append(f"segments {code}: reused (<3h)")
                write(f"segments-{code}", publish.public_segments(seg))
            except Exception as e:  # noqa: BLE001 — a failed extra must not fail the deploy
                lines.append(f"segments {code}: FAIL {e}")

    try:
        shop = await svc.shopping()  # cached 3h inside ShoppingInsight
        write("shopping", publish.public_shopping(shop))
        lines.append(f"shopping: {len(shop['by_segment'])} segments, {len(shop.get('errors', []))} errors")
    except Exception as e:  # noqa: BLE001
        lines.append(f"shopping: FAIL {e}")

    write("meta", publish.public_meta(meta))
    lines.append(f"wrote {out} (encrypted)")
    return lines
