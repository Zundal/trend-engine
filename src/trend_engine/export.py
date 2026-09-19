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

from . import archive, publish
from .health import Health
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


async def export_site(svc: TrendService, out: Path, regions: list[str], archive_dir: Path | None = None,
                      health_path: Path | None = None) -> list[str]:
    key = publish.data_key()
    health = Health()
    root = archive_dir or svc.archive_root
    today = archive.kst_today()
    seg_today: dict | None = None
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
        health.check_report(code, report)
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
                if code == "KR":
                    seg_today = publish.public_segments(seg)
            except Exception as e:  # noqa: BLE001 — a failed extra must not fail the deploy
                lines.append(f"segments {code}: FAIL {e}")
                health.problem(f"[{code}] 연령·성별 분석 실패 — {str(e)[:160]}")

    shop_today = None
    for days, name in ((7, "shopping"), (30, "shopping-month")):
        try:
            shop = await svc.shopping(days=days)  # cached (7d: 3h, 30d: 24h)
            write(name, publish.public_shopping(shop))
            if days == 7:
                shop_today = publish.public_shopping(shop)
            lines.append(f"{name}: {len(shop['by_segment'])} segments, {len(shop.get('errors', []))} errors")
            errs = shop.get("errors", [])
            if errs and len(errs) >= len(shop.get("categories", [])):
                health.problem(f"{name}: 쇼핑 수집 대부분 실패 ({len(errs)}건) — {errs[0][:120]}")
            elif errs:
                health.warn(f"{name}: 일부 실패 {len(errs)}건 — {errs[0][:120]}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"{name}: FAIL {e}")
            health.problem(f"{name}: 쇼핑 수집 실패 — {str(e)[:160]}")

    # --- 10·20대 focus (Korea)
    youth_today = None
    if "KR" in regions:
        try:
            y = await svc.youth()  # cached 3h
            write("youth", y)
            youth_today = y["discover"]
            lines.append("youth: " + ", ".join(f"{g} {len(v)}" for g, v in y["discover"]["groups"].items())
                         + f" (from {y['discover'].get('candidates')} candidates)")
            if not any(y["discover"]["groups"].values()):
                health.problem(f"10·20대: 후보 {y['discover'].get('candidates')}개 중 결과 0 — 연령 데이터 이상 의심")
        except Exception as e:  # noqa: BLE001
            lines.append(f"youth: FAIL {e}")
            health.problem(f"10·20대 분석 실패 — {str(e)[:160]}")

    # --- 세대 확산 감지 (daily, cached 20h; past cases monthly)
    if "KR" in regions:
        try:
            dif = await svc.diffusion()
            write("diffusion", dif)
            stages: dict[str, int] = {}
            for i in dif["tracked"]["items"]:
                stages[i["stage"]] = stages.get(i["stage"], 0) + 1
            lines.append(f"diffusion: {len(dif['tracked']['items'])} tracked {stages}, {len(dif['cases']['items'])} cases")
            if not dif["tracked"]["items"]:
                health.warn("세대 확산: 추적 키워드 0개")
            if not dif["cases"]["items"]:
                health.problem("세대 확산: 과거 사례 계산 결과 0개")
        except Exception as e:  # noqa: BLE001
            lines.append(f"diffusion: FAIL {e}")
            health.problem(f"세대 확산 분석 실패 — {str(e)[:160]}")

    # --- history: remember today's snapshots, archive finished days, build period views
    archive.record_daily_extras(svc.store, today, seg_today, shop_today, youth_today)
    done = archive.finalize(svc.store, root, regions, today)
    lines.append(f"archive: {len(done)} new files" + (f" ({', '.join(done[:4])}{'…' if len(done) > 4 else ''})" if done else ""))
    for code in regions:
        periods = {name: archive.period_trends(svc.store, root, code, n, today) for name, n in archive.PERIODS.items()}
        write(f"period-{code}", periods)
    ages = {name: archive.period_segments(svc.store, root, n, today) for name, n in archive.PERIODS.items()}
    write("age-period", ages)
    write("youth-period", {name: archive.period_segments(svc.store, root, n, today, kind="youth", top_n=8, limit=15)
                           for name, n in archive.PERIODS.items()})
    lines.append(f"periods: week {ages['week']['days_available']}d / month {ages['month']['days_available']}d of 연령 history")
    svc.store.prune()

    write("meta", publish.public_meta(meta))
    lines.append(f"wrote {out} (encrypted)")
    if health_path:
        health.write(health_path)
    lines.append(f"health: {'OK' if health.ok else f'{len(health.problems)} problems'}"
                 + (f", {len(health.warnings)} warnings" if health.warnings else ""))
    return lines
