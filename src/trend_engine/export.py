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

        # 교체율·쏠림: years of past daily rank lists, so this works for every country from day one
        try:
            att = await svc.attention(code)
            write(f"attention-{code}", publish.public_attention(att) if att else {})
            if att:
                t = att["summary"].get("turnover")
                lines.append(f"attention {code}: {att['days']}d, 쏠림 {att['summary']['concentration']['value']:.0%}"
                             + (f", 교체 {t['new_of_n']}/{t['n']}" if t else "")
                             + (f" (+{att['filling']}d still to fetch)" if att.get("filling") else ""))
            else:
                lines.append(f"attention {code}: not enough days yet")
        except Exception as e:  # noqa: BLE001 — an extra card must not fail the deploy
            lines.append(f"attention {code}: FAIL {e}")
            health.warn(f"[{code}] 교체율·쏠림 계산 실패 — {str(e)[:160]}")

        try:  # 유행의 모양: how each riser got its attention (readable a week after its peak)
            sh = await svc.shapes(code)
            write(f"shapes-{code}", publish.public_shapes(sh) if sh else {})
            if sh and sh["items"]:
                lines.append(f"shapes {code}: {len(sh['items'])} items {sh['mix']}")
                if sh.get("errors"):
                    health.warn(f"[{code}] 유행의 모양: 일부 조회 실패 — {sh['errors'][0][:120]}")
            else:
                lines.append(f"shapes {code}: none readable yet")
        except Exception as e:  # noqa: BLE001
            lines.append(f"shapes {code}: FAIL {e}")
            health.warn(f"[{code}] 유행의 모양 계산 실패 — {str(e)[:160]}")

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
    dif_result: dict[str, Any] | None = None
    if "KR" in regions:
        try:
            dif = dif_result = await svc.diffusion()
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

    # --- 세대 전달 함수 (커널): needs the weekly series diffusion just fetched, so it runs after it
    if "KR" in regions:
        try:
            tr = await svc.transfer()
            if tr:
                write("transfer", publish.public_transfer(tr))
                c = tr.get("contrast")
                lines.append("transfer: " + ", ".join(f"{n} {g['n_keywords']}개" for n, g in tr["groups"].items())
                             + (f", 동시분 유행 {c['fad_instant']:.0%} vs 일반 {c['plain_instant']:.0%}" if c else ""))
            else:
                lines.append("transfer: not enough series yet")
        except Exception as e:  # noqa: BLE001
            lines.append(f"transfer: FAIL {e}")
            health.warn(f"세대 전달 함수 실패 — {str(e)[:160]}")

    # --- 알림 (watchlist + 변화 감지) → 암호화 카드 + 공개 RSS 피드
    if "KR" in regions:
        try:
            from . import alerts as alerts_mod

            al = await svc.alerts(dif_result)
            write("alerts", al)
            (out / "feed.xml").write_text(alerts_mod.to_rss(al["recent"], svc.settings.site_url), encoding="utf-8")
            lines.append(f"alerts: {len(al['new'])} new, {len(al['recent'])} in feed, watchlist {len(al['watchlist'])}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"alerts: FAIL {e}")
            health.problem(f"알림 생성 실패 — {str(e)[:160]}")

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
    write("youth-trend", archive.category_shares(svc.store, root, 30, today))
    lines.append(f"periods: week {ages['week']['days_available']}d / month {ages['month']['days_available']}d of 연령 history")
    svc.store.prune()

    from .segments import FALLBACK_EVENTS

    if FALLBACK_EVENTS:  # rescued, but a path is failing — worth knowing before the backup fails too
        health.warn(f"네이버 연령 데이터: 기본 경로 실패 {len(FALLBACK_EVENTS)}회 → 예비 경로로 대체 ({FALLBACK_EVENTS[0]})")
        FALLBACK_EVENTS.clear()
    write("meta", publish.public_meta(meta))
    lines.append(f"wrote {out} (encrypted)")
    if health_path:
        health.write(health_path)
    lines.append(f"health: {'OK' if health.ok else f'{len(health.problems)} problems'}"
                 + (f", {len(health.warnings)} warnings" if health.warnings else ""))
    return lines
